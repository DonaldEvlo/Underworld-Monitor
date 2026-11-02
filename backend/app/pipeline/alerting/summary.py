"""Agregation des detections rattachees a une entite surveillee, pour la
vue d'ensemble par organisation (voir api/routers/stats.py). Logique pure
(voir CONTRIBUTING.md §3.3) : combine matching.py (rattachement) et rules.py
(severite), deja ecrits et testes separement, sans toucher la DB.

Ne persiste rien : c'est une vue de reporting/analyse, pas une AlertContract
(voir contracts/alert.py, toujours non branchee sur une table). Une detection
peut apparaitre dans le resume de plusieurs entites si elle matche plusieurs
selecteurs (ex: deux entites du meme groupe declarant le meme domaine)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.contracts.alert import AlertSeverity
from app.contracts.detection import DetectionContract
from app.contracts.entity import EntityContract
from app.pipeline.alerting.matching import matching_entities
from app.pipeline.alerting.rules import severity_for_detection

# Nombre de detections recentes gardees en detail dans le resume -- une
# entite tres exposee peut avoir des centaines de detections rattachees, pas
# la peine de toutes les remonter dans une vue d'ensemble (voir
# api/routers/stats.py pour le detail complet si besoin plus tard).
RECENT_DETECTIONS_LIMIT = 10


class RecentDetection(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    type: str
    value_masked: str
    severity: AlertSeverity
    created_at: datetime


class EntitySummary(BaseModel):
    """Vue d'ensemble des detections rattachees a une entite -- reporting,
    pas une alerte persistee."""

    model_config = {"extra": "forbid"}

    entity_id: str
    entity_name: str
    total_detections: int
    counts_by_type: dict[str, int]
    counts_by_severity: dict[AlertSeverity, int]
    recent_detections: list[RecentDetection]


def summarize_entity(
    entity: EntityContract, detections: list[DetectionContract]
) -> EntitySummary:
    """Filtre `detections` sur celles qui matchent `entity` (voir
    matching.py), calcule leur severite (voir rules.py) et agrege. Le tri des
    `recent_detections` se fait sur `created_at` decroissant."""
    matched = [d for d in detections if entity in matching_entities(d, [entity])]

    counts_by_type: dict[str, int] = {}
    counts_by_severity: dict[AlertSeverity, int] = {}
    scored: list[tuple[DetectionContract, AlertSeverity]] = []

    for detection in matched:
        counts_by_type[detection.type.value] = (
            counts_by_type.get(detection.type.value, 0) + 1
        )
        # ⚠️ `matches_watched_entity=True` est INDISPENSABLE ici : `matched`
        # ne contient, par construction, que des detections deja rattachees a
        # `entity`. L'omettre faisait calculer une severite differente de
        # celle de l'alerting -- la page Statistiques affichait LOW la ou
        # l'alerte disait MEDIUM, sur exactement la meme detection.
        # Incoherence relevee le 2026-09-01, corrigee le 2026-09-04.
        severity = severity_for_detection(detection, matches_watched_entity=True)
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1
        scored.append((detection, severity))

    scored.sort(key=lambda pair: pair[0].created_at, reverse=True)

    return EntitySummary(
        entity_id=str(entity.id),
        entity_name=entity.name,
        total_detections=len(matched),
        counts_by_type=counts_by_type,
        counts_by_severity=counts_by_severity,
        recent_detections=[
            RecentDetection(
                id=str(d.id),
                type=d.type.value,
                value_masked=d.value_masked,
                severity=severity,
                created_at=d.created_at,
            )
            for d, severity in scored[:RECENT_DETECTIONS_LIMIT]
        ],
    )
