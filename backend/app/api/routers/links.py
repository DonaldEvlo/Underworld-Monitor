"""Verification de vivacite des liens mentionnes dans les documents collectes.

Repond a "les annonces collectees sont-elles fiables ?" -- voir
services/link_health_service.py. Ne persiste rien : le resultat est calcule et
retourne, jamais stocke (aucune metadonnee de lien tiers ne reste en base).

Requetes sortantes : cet endpoint declenche du trafic Tor vers des hotes
tiers. Il est donc volontairement synchrone et borne (voir _MAX_DOCUMENTS) --
l'appelant attend le resultat, ce qui rend le cout visible plutot que de
lancer une exploration en tache de fond a chaque clic. La passe complete sur
tout le corpus passe par le worker (voir worker/tasks/link_tasks.py)."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.services.link_health_service import check_corpus_links

router = APIRouter(
    prefix="/api/links",
    tags=["links"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Borne haute du declenchement manuel : au-dela, la requete HTTP resterait
# ouverte plusieurs minutes (Tor + delais de politesse). La passe complete est
# le travail du worker, pas d'un clic.
_MAX_DOCUMENTS = 500


class LinkHealthItem(BaseModel):
    model_config = {"extra": "forbid"}

    url: str
    host: str
    is_onion: bool
    status: str
    http_status: int | None
    # Titre de la page cible, seule donnee de contenu remontee -- suffit a
    # qualifier un lien ("File not found", "Login required") sans rapatrier
    # la page. Voir pipeline/enrich/link_health.py.
    title: str | None
    content_type: str | None
    content_length: int | None


class LinkHealthResponse(BaseModel):
    model_config = {"extra": "forbid"}

    documents_scanned: int
    documents_with_links: int
    hosts_checked: int
    counts_by_status: dict[str, int]
    alive_ratio: float | None
    items: list[LinkHealthItem]


@router.post("/check", response_model=LinkHealthResponse)
def check_links(
    db: Session = Depends(get_db),
    source_id: uuid.UUID | None = None,
    limit_documents: int = Query(default=100, ge=1, le=_MAX_DOCUMENTS),
) -> LinkHealthResponse:
    """Verifie la vivacite des liens mentionnes dans les `limit_documents`
    documents les plus recents (optionnellement restreints a une source).

    Ne telecharge jamais le contenu des liens : uniquement statut HTTP, titre
    et en-tetes (voir pipeline/enrich/link_health.py). Un lien vers un
    hebergeur de fuite est verifie comme les autres -- savoir qu'un dump est
    toujours en ligne est un signal de gravite pour l'analyste, le rapatrier
    serait interdit (CONTRIBUTING.md §2)."""
    report = check_corpus_links(
        db, source_id=source_id, limit_documents=limit_documents
    )
    return LinkHealthResponse(
        documents_scanned=report.documents_scanned,
        documents_with_links=report.documents_with_links,
        hosts_checked=report.hosts_checked,
        counts_by_status=report.counts_by_status,
        alive_ratio=report.alive_ratio,
        items=[
            LinkHealthItem(
                url=r.url,
                host=r.host,
                is_onion=r.is_onion,
                status=r.status.value,
                http_status=r.http_status,
                title=r.title,
                content_type=r.content_type,
                content_length=r.content_length,
            )
            for r in report.results
        ],
    )
