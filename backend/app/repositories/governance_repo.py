"""Lecture des alertes pour la vue de gouvernance : colonnes AGREGEABLES
seulement (gravite, statut, secteur, pays, gang, credibilite, dates). Aucune
valeur detectee, aucun titre de document -- voir pipeline/reporting/governance.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.pipeline.reporting.governance import AlertFact


def alert_facts(db: Session) -> list[AlertFact]:
    lignes = db.query(
        Alert.alert_date,
        Alert.created_at,
        Alert.severity,
        Alert.status,
        Alert.victim_sector,
        Alert.victim_country,
        Alert.corroborated_group,
        Alert.credibility_level,
        Alert.acknowledged_at,
        Alert.resolved_at,
        Alert.resolution_reason,
    ).all()
    return [
        AlertFact(
            alert_date=ligne.alert_date,
            created_at=ligne.created_at,
            severity=ligne.severity,
            status=ligne.status,
            sector=ligne.victim_sector,
            country=ligne.victim_country,
            gang=ligne.corroborated_group,
            credibility=ligne.credibility_level,
            acknowledged_at=ligne.acknowledged_at,
            resolved_at=ligne.resolved_at,
            resolution_reason=ligne.resolution_reason,
        )
        for ligne in lignes
    ]
