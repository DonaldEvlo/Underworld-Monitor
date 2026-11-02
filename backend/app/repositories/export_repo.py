"""Requetes des exports CSV (`/api/exports`), sorties du routeur.

Le routeur garde la mise en forme (colonnes, masquage deja fait en base,
apercu borne) ; ici, uniquement la lecture. Requetes deplacees a l'identique
le 2026-09-25 (voir CONTRIBUTING.md §3.3).
"""

from __future__ import annotations

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source


class ExportRepository:
    def __init__(self, db: Session):
        self.db = db

    def alerts(
        self, *, status: str | None, severity: list[str] | None, limit: int
    ) -> list[Alert]:
        requete = self.db.query(Alert)
        if status:
            requete = requete.filter(Alert.status == status)
        if severity:
            requete = requete.filter(Alert.severity.in_(severity))
        return requete.order_by(Alert.created_at.desc()).limit(limit).all()

    def detections(
        self, *, q: str | None, type_: str | None, limit: int
    ) -> list[Row[Detection, RawDocument, Source]]:
        requete = (
            self.db.query(Detection, RawDocument, Source)
            .join(RawDocument, RawDocument.id == Detection.document_id)
            .join(Source, Source.id == RawDocument.source_id)
        )
        if q:
            requete = requete.filter(Detection.value_masked.ilike(f"%{q.strip()}%"))
        if type_:
            requete = requete.filter(Detection.type == type_)
        return requete.order_by(Detection.created_at.desc()).limit(limit).all()

    def documents(
        self, *, q: str | None, source_id: str | None, limit: int
    ) -> list[Row[RawDocument, Source]]:
        requete = self.db.query(RawDocument, Source).join(
            Source, Source.id == RawDocument.source_id
        )
        if q:
            requete = requete.filter(RawDocument.title.ilike(f"%{q.strip()}%"))
        if source_id:
            requete = requete.filter(RawDocument.source_id == source_id)
        return requete.order_by(RawDocument.fetched_at.desc()).limit(limit).all()

    def alert_detections(
        self, alert_id: str
    ) -> list[Row[Detection, RawDocument, Source]]:
        return (
            self.db.query(Detection, RawDocument, Source)
            .join(AlertDetection, AlertDetection.detection_id == Detection.id)
            .join(RawDocument, RawDocument.id == Detection.document_id)
            .join(Source, Source.id == RawDocument.source_id)
            .filter(AlertDetection.alert_id == alert_id)
            .all()
        )
