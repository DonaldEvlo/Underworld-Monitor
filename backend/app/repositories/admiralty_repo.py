"""Requetes de la notation Admiralty : historique des sources, sources des
alertes. Deux agregats, quel que soit le nombre d'alertes servies."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.alert import AlertDetection
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source


def source_track_rows(db: Session) -> list[tuple[uuid.UUID, str, str | None, int, int]]:
    """Par (source, collecteur) : nom, victimes evaluees, victimes confirmees.

    Une victime = un document ; « evaluee » = au moins une detection
    `domain`/`organization` confrontee aux agregateurs (corroboree ou
    exclusive) -- `not_applicable` et NULL ne comptent pas."""
    statut = Detection.corroboration_status
    evaluees = func.count(func.distinct(RawDocument.id)).filter(
        statut.in_(("corroborated", "exclusive"))
    )
    confirmees = func.count(func.distinct(RawDocument.id)).filter(
        statut == "corroborated"
    )
    lignes = (
        db.query(Source.id, Source.name, RawDocument.collector, evaluees, confirmees)
        .join(RawDocument, RawDocument.source_id == Source.id)
        .outerjoin(
            Detection,
            (Detection.document_id == RawDocument.id)
            & Detection.type.in_(("domain", "organization")),
        )
        .group_by(Source.id, Source.name, RawDocument.collector)
        .all()
    )
    return [(r[0], r[1], r[2], int(r[3] or 0), int(r[4] or 0)) for r in lignes]


def alert_victim_titles(
    db: Session, alert_ids: Iterable[uuid.UUID], collectors: Iterable[str]
) -> dict[uuid.UUID, list[str]]:
    """Titres DISTINCTS des documents de sites de victimes rattaches a chaque
    alerte (un document de site de fuite = une victime, son titre la nomme).
    Ordre stable : alphabetique."""
    ids = list(alert_ids)
    if not ids:
        return {}
    lignes = (
        db.query(AlertDetection.alert_id, RawDocument.title)
        .join(Detection, Detection.id == AlertDetection.detection_id)
        .join(RawDocument, RawDocument.id == Detection.document_id)
        .filter(
            AlertDetection.alert_id.in_(ids),
            RawDocument.collector.in_(list(collectors)),
            RawDocument.title.isnot(None),
        )
        .distinct()
        .all()
    )
    titres: dict[uuid.UUID, set[str]] = {}
    for alert_id, titre in lignes:
        if titre:  # deja filtre en SQL (isnot(None))
            titres.setdefault(alert_id, set()).add(titre.strip())
    return {k: sorted(v) for k, v in titres.items()}


def alert_victim_claims(
    db: Session, alert_id: uuid.UUID, collectors: Iterable[str]
) -> list[tuple[str, str | None]]:
    """(victime, gang) de chaque victime d'une alerte : titre du document de
    site de fuite et gang corrobore porte par SA detection. Ordre stable.

    Repli sur `source_meta.group_name` : un document RansomLook nomme le gang
    mais ses detections ne sont jamais corroborees (ce serait une
    auto-confirmation), si bien que `pharma-exemple.ma` (inc ransom) sortait « sans
    gang » alors que l'annonce le nomme."""
    lignes = (
        db.query(
            RawDocument.title, Detection.corroborated_group, RawDocument.source_meta
        )
        .join(Detection, Detection.document_id == RawDocument.id)
        .join(AlertDetection, AlertDetection.detection_id == Detection.id)
        .filter(
            AlertDetection.alert_id == alert_id,
            RawDocument.collector.in_(list(collectors)),
            RawDocument.title.isnot(None),
        )
        .distinct()
        .all()
    )
    gangs: dict[str, str | None] = {}
    for titre, gang, meta in lignes:
        titre = titre.strip()
        if not gang and isinstance(meta, dict):
            gang = meta.get("group_name") or None
        if gangs.get(titre) is None:
            gangs[titre] = gang
    return sorted(gangs.items())


def alert_source_rows(
    db: Session, alert_ids: Iterable[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, str | None]]:
    """(alerte, source, collecteur) distincts pour les alertes demandees."""
    ids = list(alert_ids)
    if not ids:
        return []
    lignes = (
        db.query(AlertDetection.alert_id, RawDocument.source_id, RawDocument.collector)
        .join(Detection, Detection.id == AlertDetection.detection_id)
        .join(RawDocument, RawDocument.id == Detection.document_id)
        .filter(AlertDetection.alert_id.in_(ids))
        .distinct()
        .all()
    )
    return [(r[0], r[1], r[2]) for r in lignes]
