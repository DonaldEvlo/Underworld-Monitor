"""Export CSV : faire SORTIR ce que l'analyste voit.

⚠️ Aucun export n'existait nulle part. Pour transmettre un dossier a une
victime ou l'archiver, il fallait des captures d'ecran.

⚠️ CONFORMITE. On n'exporte que ce que l'interface affiche deja : valeurs
MASQUEES, metadonnees, liens. Jamais `value_hash` (correlation interne),
jamais le contenu integral d'un document (regle 2) -- seul un apercu borne,
qui est l'annonce publique de l'attaquant.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.roles import PEUT_TRAITER_LES_ALERTES
from app.api.deps import exige_role, get_db
from app.repositories.entity_repo import EntityRepository
from app.repositories.export_repo import ExportRepository

router = APIRouter(
    prefix="/api/exports",
    tags=["exports"],
    dependencies=[Depends(exige_role(PEUT_TRAITER_LES_ALERTES))],
)

# Borne haute d'un export. Au-dela, un CSV n'est plus lisible et la requete
# devient couteuse : mieux vaut filtrer avant.
_MAX_LIGNES = 5_000

_APERCU = 300


# Caractères qui font interpréter une cellule comme une FORMULE par Excel ou
# LibreOffice. ⚠️ Les exports contiennent des titres et extraits publiés par des
# ATTAQUANTS (sites de fuite, forums) : un titre « =HYPERLINK(...) » ou
# « @SUM(...) » s'exécuterait à l'ouverture du fichier par l'analyste
# (injection de formule CSV, constatée à l'audit du 2026-10-06).
_DEBUT_DE_FORMULE = ("=", "+", "-", "@", "\t", "\r")


def cellule_sure(valeur):
    """Neutralise une cellule texte qui commencerait comme une formule, en la
    préfixant d'une apostrophe (convention OWASP) : le tableur l'affiche
    comme du texte. Les nombres et les valeurs vides passent tels quels."""
    if isinstance(valeur, str) and valeur.startswith(_DEBUT_DE_FORMULE):
        return "'" + valeur
    return valeur


def _csv(entetes: list[str], lignes, nom: str) -> Response:
    tampon = io.StringIO()
    # ⚠️ `;` et BOM : Excel en francais n'ouvre correctement un CSV que dans
    # ces conditions. Un export illisible par le tableur de l'analyste ne sert
    # a rien.
    ecrivain = csv.writer(tampon, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    ecrivain.writerow(entetes)
    ecrivain.writerows([cellule_sure(v) for v in ligne] for ligne in lignes)
    horodatage = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + tampon.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nom}-{horodatage}.csv"'
        },
    )


@router.get("/alerts.csv")
def export_alerts(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    severity: list[str] | None = Query(default=None),
) -> Response:
    """Alertes, avec leur qualification et leur etat de verification."""
    noms = EntityRepository(db).names_by_id()
    lignes = []
    for alerte in ExportRepository(db).alerts(
        status=status, severity=severity, limit=_MAX_LIGNES
    ):
        lignes.append(
            [
                noms.get(alerte.entity_id)
                or (f"{alerte.region} - victime non declaree" if alerte.region else ""),
                alerte.severity,
                alerte.status,
                alerte.resolution_reason or "",
                alerte.assignee or "",
                alerte.alert_date.isoformat(),
                len(alerte.detections),
                alerte.corroboration_status or "",
                alerte.corroborated_group or "",
                alerte.corroboration_evidence_url or "",
                alerte.press_source_url or alerte.press_evidence_url or "",
                alerte.credibility_level or "",
                alerte.credibility_evidence or "",
                (alerte.summary or "").replace("\n", " ")[:600],
            ]
        )
    return _csv(
        [
            "organisation",
            "gravite",
            "statut",
            "qualification",
            "affecte_a",
            "date_alerte",
            "detections",
            "verification_externe",
            "groupe_attaquant",
            "lien_preuve",
            "confirmation_presse",
            "credibilite",
            "preuve_credibilite",
            "resume",
        ],
        lignes,
        "alertes",
    )


@router.get("/detections.csv")
def export_detections(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
) -> Response:
    """Detections, valeurs MASQUEES uniquement."""
    lignes = [
        [
            detection.type,
            detection.value_masked or "",
            detection.severity or "",
            "oui" if detection.validated else "non",
            "oui" if detection.is_relevant else "non",
            detection.corroboration_status or "",
            detection.corroborated_group or "",
            source.name,
            (document.title or "")[:120],
            document.url or "",
            detection.created_at.isoformat(),
        ]
        for detection, document, source in ExportRepository(db).detections(
            q=q, type_=type, limit=_MAX_LIGNES
        )
    ]
    return _csv(
        [
            "type",
            "valeur_masquee",
            "gravite",
            "validee",
            "pertinente",
            "verification_externe",
            "groupe_attaquant",
            "source",
            "document",
            "url_document",
            "detectee_le",
        ],
        lignes,
        "detections",
    )


@router.get("/documents.csv")
def export_documents(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
) -> Response:
    """Documents collectes, avec un apercu borne de l'annonce publique."""
    lignes = [
        [
            (document.title or "")[:160],
            source.name,
            document.collector,
            document.announcement_class or "",
            document.published_at.isoformat() if document.published_at else "",
            document.fetched_at.isoformat() if document.fetched_at else "",
            document.url or "",
            (document.content or "").replace("\n", " ")[:_APERCU],
        ]
        for document, source in ExportRepository(db).documents(
            q=q, source_id=source_id, limit=_MAX_LIGNES
        )
    ]
    return _csv(
        [
            "titre",
            "source",
            "collecteur",
            "classe_annonce",
            "publie_le",
            "collecte_le",
            "url",
            "apercu",
        ],
        lignes,
        "documents",
    )


@router.get("/alert-detections.csv")
def export_alert_detections(alert_id: str, db: Session = Depends(get_db)) -> Response:
    """Le detail d'UNE alerte : ce qui la fonde, ligne par ligne."""
    lignes = [
        [
            detection.type,
            detection.value_masked or "",
            source.name,
            (document.title or "")[:120],
            document.url or "",
            document.published_at.isoformat() if document.published_at else "",
            detection.corroboration_status or "",
            detection.corroboration_evidence_url or "",
        ]
        for detection, document, source in ExportRepository(db).alert_detections(
            alert_id
        )
    ]
    return _csv(
        [
            "type",
            "valeur_masquee",
            "source",
            "document",
            "url_document",
            "publie_le",
            "verification_externe",
            "lien_preuve",
        ],
        lignes,
        "alerte-detail",
    )
