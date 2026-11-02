"""Le périmètre surveillé pour le RSSI : lecture en base, mise en forme pure
(`pipeline/reporting/perimeter`). Voir la docstring de ce module pour la
frontière : seuls des faits de SYNTHÈSE quittent ce service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.db.models.entity import Entity, EntitySelector
from app.pipeline.reporting.perimeter import (
    AlertSynth,
    OrgFact,
    build_perimeter,
    synthese_alerte,
    trier_alertes,
)


def _orgs(db: Session) -> list[OrgFact]:
    avec_selecteur = {
        e for (e,) in db.execute(select(EntitySelector.entity_id).distinct())
    }
    return [
        OrgFact(
            id=e.id,
            name=e.name,
            parent_id=e.parent_id,
            country=e.country,
            sector=e.sector,
            active=e.active,
            has_selectors=e.id in avec_selecteur,
        )
        for e in db.execute(select(Entity)).scalars()
    ]


def _alertes(db: Session, entity_ids: set[uuid.UUID] | None = None) -> list[AlertSynth]:
    """Alertes d'ORGANISATIONS uniquement : une alerte régionale (victime non
    déclarée) concerne un tiers, elle n'appartient pas au périmètre."""
    requete = select(Alert).where(Alert.entity_id.is_not(None))
    if entity_ids is not None:
        requete = requete.where(Alert.entity_id.in_(entity_ids))
    return [
        AlertSynth(
            id=a.id,
            entity_id=a.entity_id,
            alert_date=a.alert_date,
            severity=a.severity,
            status=a.status,
            credibility_level=a.credibility_level,
            summary=a.summary,
            resolution_reason=a.resolution_reason,
            acknowledged_at=a.acknowledged_at,
            resolved_at=a.resolved_at,
        )
        for a in db.execute(requete).scalars()
        if a.entity_id is not None
    ]


def perimetre(db: Session) -> dict:
    return build_perimeter(_orgs(db), _alertes(db))


def alertes_de(db: Session, entity_id: uuid.UUID) -> dict | None:
    """Synthèse des alertes d'une organisation, et de ses filiales si c'est
    un groupe. None si l'organisation n'existe pas."""
    entite = db.get(Entity, entity_id)
    if entite is None:
        return None
    filiales = {
        e.id: e.name
        for e in db.execute(
            select(Entity).where(Entity.parent_id == entity_id)
        ).scalars()
    }
    noms = {entity_id: entite.name, **filiales}
    alertes = trier_alertes(_alertes(db, set(noms)))
    return {
        "entity_id": str(entity_id),
        "name": entite.name,
        "alerts": [
            {**synthese_alerte(a), "organization": noms.get(a.entity_id)}
            for a in alertes
        ],
    }
