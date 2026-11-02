"""Recherche TRANSVERSE : une valeur, tout ce que la plateforme en sait.

⚠️ Repond au geste le plus banal d'un analyste -- « cette organisation
est-elle deja apparue ? » -- qui n'avait aucune reponse : la page Recherche
cherche de NOUVELLES SOURCES sur des moteurs .onion, pas dans le corpus ; la
page Detections n'avait aucun filtre par valeur ; seule la page Documents
offrait une recherche texte.

Ne fait AUCUN appel reseau : uniquement des requetes sur ce qui est deja
collecte. A ne pas confondre avec `routers/search.py`, qui interroge des
moteurs .onion pour decouvrir des sources.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.repositories.entity_repo import EntityRepository
from app.repositories.lookup_repo import LookupRepository

router = APIRouter(
    prefix="/api/lookup",
    tags=["lookup"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Bornes par famille de resultat : la recherche doit rester instantanee et
# tenir a l'ecran. Le TOTAL reel est renvoye a cote, jamais masque -- un
# compte tronque sans le dire est ce qui fait douter d'un outil.
_MAX_PAR_FAMILLE = 25


class DetectionTrouvee(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    type: str
    value_masked: str
    severity: str | None
    corroboration_status: str | None
    corroborated_group: str | None
    document_id: uuid.UUID
    document_title: str | None
    source_name: str | None
    created_at: datetime


class DocumentTrouve(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    title: str | None
    source_name: str | None
    url: str | None
    published_at: datetime | None
    fetched_at: datetime | None


class AlerteTrouvee(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    subject: str
    severity: str
    status: str
    alert_date: date
    corroboration_status: str | None


class EntiteTrouvee(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    name: str
    active: bool
    matched_selector: str | None


class LookupResponse(BaseModel):
    model_config = {"extra": "forbid"}

    query: str
    entities: list[EntiteTrouvee]
    alerts: list[AlerteTrouvee]
    detections: list[DetectionTrouvee]
    documents: list[DocumentTrouve]
    # Totaux REELS, avant troncature : « 21 detections (3 affichees) » est
    # honnete, « 3 detections » ne l'est pas.
    total_detections: int
    total_documents: int
    total_alerts: int


@router.get("", response_model=LookupResponse)
def lookup(
    q: str = Query(min_length=2, description="Domaine, organisation, mot-cle"),
    db: Session = Depends(get_db),
) -> LookupResponse:
    """Tout ce que la plateforme sait d'une valeur, en une requete."""
    terme = q.strip()
    motif = f"%{terme}%"
    depot = LookupRepository(db)

    # --- Organisations surveillees ---------------------------------------
    entites = []
    lignes_entites = depot.entities_matching(motif, _MAX_PAR_FAMILLE)
    vues: set[uuid.UUID] = set()
    for entity, selector in lignes_entites:
        if entity.id in vues:
            continue
        vues.add(entity.id)
        entites.append(
            EntiteTrouvee(
                id=entity.id,
                name=entity.name,
                active=entity.active,
                matched_selector=selector.value if selector else None,
            )
        )

    # --- Detections -------------------------------------------------------
    total_detections = depot.count_detections_matching(motif)
    lignes = depot.detections_matching(motif, _MAX_PAR_FAMILLE)
    detections = [
        DetectionTrouvee(
            id=detection.id,
            type=detection.type,
            value_masked=detection.value_masked or "",
            severity=detection.severity,
            corroboration_status=detection.corroboration_status,
            corroborated_group=detection.corroborated_group,
            document_id=document.id,
            document_title=document.title,
            source_name=source.name,
            created_at=detection.created_at,
        )
        for detection, document, source in lignes
    ]

    # --- Documents --------------------------------------------------------
    total_documents = depot.count_documents_matching(motif)
    documents = [
        DocumentTrouve(
            id=document.id,
            title=document.title,
            source_name=source.name,
            url=document.url,
            published_at=document.published_at,
            fetched_at=document.fetched_at,
        )
        for document, source in depot.documents_matching(motif, _MAX_PAR_FAMILLE)
    ]

    # --- Alertes ----------------------------------------------------------
    # Une alerte est trouvee par la VALEUR de ses detections : c'est ainsi
    # qu'un analyste la cherche (« a-t-on deja alerte sur ce domaine ? »),
    # jamais par son identifiant.
    total_alerts = depot.count_alerts_matching(motif)
    noms = EntityRepository(db).names_by_id()
    alertes = [
        AlerteTrouvee(
            id=alert.id,
            subject=(
                noms.get(alert.entity_id)
                or (
                    f"{alert.region} — victime non déclarée"
                    if alert.region
                    else "Alerte"
                )
            ),
            severity=alert.severity,
            status=alert.status,
            alert_date=alert.alert_date,
            corroboration_status=alert.corroboration_status,
        )
        for alert in depot.alerts_matching(motif, _MAX_PAR_FAMILLE)
    ]

    return LookupResponse(
        query=terme,
        entities=entites,
        alerts=alertes,
        detections=detections,
        documents=documents,
        total_detections=total_detections,
        total_documents=total_documents,
        total_alerts=total_alerts,
    )
