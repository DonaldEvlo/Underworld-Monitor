"""Requetes des statistiques (`/api/stats`), sorties du routeur.

Regle d'architecture (CONTRIBUTING.md §3.3) : les depots sont le seul endroit qui
parle a la base. Ces requetes vivaient dans `api/routers/stats.py`
(11 appels, deplaces le 2026-09-25 a l'identique -- verifie par capture des
reponses avant/apres).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source

GRAVES = ("critical", "high")


class StatsRepository:
    def __init__(self, db: Session):
        self.db = db

    def activity_counts(self, depuis: datetime) -> dict[str, int]:
        """Nouveautes depuis `depuis`, et file de travail tous jours
        confondus."""
        db = self.db
        entites_actives = db.query(Entity).filter(Entity.active.is_(True)).all()
        avec_selecteur = {
            s.entity_id for s in db.query(EntitySelector.entity_id).distinct().all()
        }
        return {
            "nouvelles_alertes": db.query(Alert)
            .filter(Alert.created_at >= depuis)
            .count(),
            "nouvelles_alertes_graves": db.query(Alert)
            .filter(Alert.created_at >= depuis, Alert.severity.in_(GRAVES))
            .count(),
            "nouveaux_documents": db.query(RawDocument)
            .filter(RawDocument.fetched_at >= depuis)
            .count(),
            "nouvelles_detections": db.query(Detection)
            .filter(Detection.created_at >= depuis)
            .count(),
            "alertes_ouvertes": db.query(Alert).filter(Alert.status == "open").count(),
            "alertes_non_affectees": db.query(Alert)
            .filter(Alert.status == "open", Alert.assignee.is_(None))
            .count(),
            "alertes_sans_resume": db.query(Alert)
            .filter(Alert.status == "open", Alert.summary.is_(None))
            .count(),
            "entites_sans_selecteur": sum(
                1 for e in entites_actives if e.id not in avec_selecteur
            ),
            "sources_en_echec": db.query(Source)
            .filter(Source.active.is_(True), Source.last_collected_at.is_(None))
            .count(),
        }

    def detections_with_document_and_source(
        self, detection_type: str, limit: int
    ) -> list[Row[Detection, RawDocument, Source]]:
        """Detections d'un type, avec leur document et leur source."""
        return (
            self.db.query(Detection, RawDocument, Source)
            .join(RawDocument, RawDocument.id == Detection.document_id)
            .join(Source, Source.id == RawDocument.source_id)
            .filter(Detection.type == detection_type)
            .limit(limit)
            .all()
        )
