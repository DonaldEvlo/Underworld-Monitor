"""Requetes de la recherche transverse (`/api/lookup`), sorties du routeur.

Une valeur -> organisations, detections, documents, alertes. Chaque famille
expose son TOTAL reel a cote de la page servie : un compte tronque sans le
dire est ce qui fait douter d'un outil. Requetes deplacees a l'identique le
2026-09-25 (voir CONTRIBUTING.md §3.3).
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import Row, or_
from sqlalchemy.orm import Session

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source


class LookupRepository:
    def __init__(self, db: Session):
        self.db = db

    def entities_matching(
        self, motif: str, limit: int
    ) -> list[Row[Entity, EntitySelector | None]]:
        # Jointure EXTERNE : le selecteur vaut None pour une entite trouvee par
        # son nom seul. Le typage de SQLAlchemy ne le sait pas, on le dit.
        return cast(
            "list[Row[Entity, EntitySelector | None]]",
            self.db.query(Entity, EntitySelector)
            .outerjoin(EntitySelector, EntitySelector.entity_id == Entity.id)
            .filter(or_(Entity.name.ilike(motif), EntitySelector.value.ilike(motif)))
            .limit(limit)
            .all(),
        )

    def count_detections_matching(self, motif: str) -> int:
        return (
            self.db.query(Detection).filter(Detection.value_masked.ilike(motif)).count()
        )

    def detections_matching(
        self, motif: str, limit: int
    ) -> list[Row[Detection, RawDocument, Source]]:
        return (
            self.db.query(Detection, RawDocument, Source)
            .join(RawDocument, RawDocument.id == Detection.document_id)
            .join(Source, Source.id == RawDocument.source_id)
            .filter(Detection.value_masked.ilike(motif))
            .order_by(Detection.created_at.desc())
            .limit(limit)
            .all()
        )

    def count_documents_matching(self, motif: str) -> int:
        return (
            self.db.query(RawDocument)
            .filter(
                or_(RawDocument.title.ilike(motif), RawDocument.content.ilike(motif))
            )
            .count()
        )

    def documents_matching(
        self, motif: str, limit: int
    ) -> list[Row[RawDocument, Source]]:
        return (
            self.db.query(RawDocument, Source)
            .join(Source, Source.id == RawDocument.source_id)
            .filter(
                or_(RawDocument.title.ilike(motif), RawDocument.content.ilike(motif))
            )
            .order_by(RawDocument.fetched_at.desc())
            .limit(limit)
            .all()
        )

    def _alertes_par_valeur(self, motif: str):
        """Une alerte est trouvee par la VALEUR de ses detections : c'est ainsi
        qu'un analyste la cherche, jamais par son identifiant."""
        return (
            self.db.query(Alert)
            .join(AlertDetection, AlertDetection.alert_id == Alert.id)
            .join(Detection, Detection.id == AlertDetection.detection_id)
            .filter(Detection.value_masked.ilike(motif))
            .distinct()
        )

    def count_alerts_matching(self, motif: str) -> int:
        return self._alertes_par_valeur(motif).count()

    def alerts_matching(self, motif: str, limit: int) -> list[Alert]:
        return (
            self._alertes_par_valeur(motif)
            .order_by(Alert.created_at.desc())
            .limit(limit)
            .all()
        )
