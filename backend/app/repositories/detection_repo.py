from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.contracts.detection import DetectionContract, DetectionType
from app.db.models.detection import Detection
from app.repositories.alert_repo import AlertRepository


class DetectionSortBy(str, Enum):
    CREATED_AT = "created_at"
    TYPE = "type"
    VALUE_MASKED = "value_masked"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class DetectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, detection_id: uuid.UUID) -> Detection | None:
        return self.db.query(Detection).filter(Detection.id == detection_id).first()

    def list_for_document(self, document_id: uuid.UUID) -> list[Detection]:
        return list(
            self.db.query(Detection).filter(Detection.document_id == document_id).all()
        )

    def _filtered_query(
        self,
        type_: str | None,
        validated: bool | None,
        is_relevant: bool | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        types_: Sequence[str] | None = None,
        search: str | None = None,
    ):
        query = self.db.query(Detection)
        if search:
            # ⚠️ Recherche sur la valeur MASQUEE, la seule que l'on conserve.
            # Elle manquait entierement : « cette organisation est-elle deja
            # apparue ? » -- le geste le plus banal d'un analyste -- n'avait
            # aucune reponse cote detections, et l'etape 5 du dossier de
            # demonstration (« filtrer sur institution-exemple ») n'etait pas
            # realisable.
            query = query.filter(Detection.value_masked.ilike(f"%{search.strip()}%"))
        if type_ is not None:
            query = query.filter(Detection.type == type_)
        # `types_` sert aux appelants qui croisent le corpus en memoire et ne
        # savent traiter qu'une partie des types (voir
        # alerting/matching.py::MATCHABLE_DETECTION_TYPES) : filtrer ici plutot
        # qu'apres coup evite que leur plafond de lignes soit consomme par des
        # detections jetees juste apres. Une sequence vide filtre a vide, ce
        # qui est le comportement attendu (aucun type demande = aucune ligne)
        # et non un no-op silencieux.
        if types_ is not None:
            query = query.filter(Detection.type.in_(list(types_)))
        if validated is not None:
            query = query.filter(Detection.validated == validated)
        if is_relevant is not None:
            query = query.filter(Detection.is_relevant == is_relevant)
        if created_from is not None:
            query = query.filter(Detection.created_at >= created_from)
        if created_to is not None:
            query = query.filter(Detection.created_at <= created_to)
        return query

    def _apply_sort(self, query, sort_by: DetectionSortBy, sort_order: SortOrder):
        column = {
            DetectionSortBy.TYPE: Detection.type,
            DetectionSortBy.VALUE_MASKED: Detection.value_masked,
        }.get(sort_by, Detection.created_at)
        ordered = column.asc() if sort_order == SortOrder.ASC else column.desc()
        return query.order_by(ordered)

    def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        type_: str | None = None,
        validated: bool | None = None,
        is_relevant: bool | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: DetectionSortBy = DetectionSortBy.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
        types_: Sequence[str] | None = None,
        search: str | None = None,
    ) -> list[Detection]:
        query = self._filtered_query(
            type_, validated, is_relevant, created_from, created_to, types_, search
        )
        query = self._apply_sort(query, sort_by, sort_order)
        return list(query.offset(offset).limit(limit).all())

    def count_all(
        self,
        type_: str | None = None,
        validated: bool | None = None,
        is_relevant: bool | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        types_: Sequence[str] | None = None,
        search: str | None = None,
    ) -> int:
        return self._filtered_query(
            type_, validated, is_relevant, created_from, created_to, types_, search
        ).count()

    def count_by_type(self) -> dict[str, int]:
        rows = (
            self.db.query(Detection.type, func.count(Detection.id))
            .group_by(Detection.type)
            .all()
        )
        return {type_: count for type_, count in rows}

    def top_organization_candidates(
        self, limit: int = 50
    ) -> list[tuple[str, str, int]]:
        """Detections ORGANIZATION les plus frequentes, groupees par valeur
        normalisee -- base des "entites candidates" proposees a l'analyste
        (voir pipeline/alerting/candidates.py). Groupe par (value_masked,
        value_hash) ensemble, pas juste value_masked, pour ne jamais fusionner
        deux hachages differents par erreur."""
        rows = (
            self.db.query(
                Detection.value_masked,
                Detection.value_hash,
                func.count(Detection.id),
            )
            .filter(Detection.type == DetectionType.ORGANIZATION.value)
            .group_by(Detection.value_masked, Detection.value_hash)
            .order_by(func.count(Detection.id).desc())
            .limit(limit)
            .all()
        )
        return [
            (value_masked, value_hash, count)
            for value_masked, value_hash, count in rows
        ]

    def document_ids_for_value(self, type_: str, value_masked: str) -> list[uuid.UUID]:
        """Documents portant une détection de ce type et de cette valeur
        (masquée), du plus récent au plus ancien : « où est-ce cité ? »."""
        rows = (
            self.db.query(Detection.document_id, func.max(Detection.created_at))
            .filter(Detection.type == type_, Detection.value_masked == value_masked)
            .group_by(Detection.document_id)
            .order_by(func.max(Detection.created_at).desc())
            .all()
        )
        return [document_id for document_id, _ in rows]

    def topics_for_documents(
        self, document_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Rubrique de classement (voir patterns/topic.py) par document, pour
        une liste d'ids connue. Chargement groupe en une requete plutot qu'un
        appel par ligne affichee (voir api/routers/detections.py::_list_item,
        deja coûteux en requetes). Un document appartient a une seule rubrique
        en pratique ; si plusieurs existent, la premiere par date est gardee."""
        if not document_ids:
            return {}
        rows = (
            self.db.query(Detection.document_id, Detection.value_masked)
            .filter(
                Detection.type == DetectionType.SOURCE_TOPIC.value,
                Detection.document_id.in_(document_ids),
            )
            .order_by(Detection.created_at.asc())
            .all()
        )
        topics: dict[uuid.UUID, str] = {}
        for document_id, value_masked in rows:
            topics.setdefault(document_id, value_masked)
        return topics

    def exists_for_document(
        self, document_id: uuid.UUID, value_hash: str, type_: str | None = None
    ) -> bool:
        """True si une detection (document_id, value_hash) existe deja -- utilise
        par les backfills (voir api/routers/entities.py) pour ne pas dupliquer a
        chaque relance, faute de passer par la dedup automatique de detect_all.

        `type_` restreint la verification a un type : `value_hash` ne porte que
        sur la valeur, donc une meme chaine detectee sous deux types differents
        partage le meme hash (constate : "t.me" existe en `domain` ET doit
        pouvoir exister en `distribution_channel`). Sans ce filtre, un backfill
        d'un nouveau type croit a tort que la detection existe deja. Laisser
        `None` conserve le comportement historique (tous types confondus)."""
        query = self.db.query(Detection.id).filter(
            Detection.document_id == document_id, Detection.value_hash == value_hash
        )
        if type_ is not None:
            query = query.filter(Detection.type == type_)
        return query.first() is not None

    def with_declared_victim_country(
        self, *, created_from: datetime | None = None
    ) -> list[tuple[Detection, dict]]:
        """Detections `organization` des documents dont le pays de la victime
        a ete DECLARE par un agregateur (`source_meta.victim_country`, voir
        services/victim_location_service), avec le `source_meta` du document."""
        from app.db.models.raw_document import RawDocument

        requete = (
            self.db.query(Detection, RawDocument.source_meta)
            .join(RawDocument, RawDocument.id == Detection.document_id)
            .filter(
                Detection.type == DetectionType.ORGANIZATION.value,
                RawDocument.source_meta["victim_country"].astext.isnot(None),
            )
        )
        if created_from is not None:
            requete = requete.filter(Detection.created_at >= created_from)
        return [(d, meta or {}) for d, meta in requete.all()]

    def delete_all(self) -> int:
        """Supprime toutes les detections. Appele avant de vider raw_documents
        (voir RawDocumentRepository.delete_all) -- la contrainte de cle
        etrangere detections.document_id interdit sinon la suppression des
        documents tant que leurs detections existent encore.

        Vide d'abord alerts/alert_detections (voir AlertRepository.delete_all)
        : depuis la migration 0011, alert_detections.detection_id est aussi
        une FK vers detections -- une alerte ne peut pas survivre a la
        suppression des detections qui l'ont declenchee."""
        AlertRepository(self.db).delete_all()
        count = self.db.query(Detection).count()
        self.db.query(Detection).delete()
        self.db.commit()
        return count

    def save_all(self, detections: list[DetectionContract]) -> list[Detection]:
        if not detections:
            return []
        rows = [
            Detection(
                id=d.id,
                document_id=d.document_id,
                type=d.type.value,
                value_masked=d.value_masked,
                value_hash=d.value_hash,
                validated=d.validated,
                is_relevant=d.is_relevant,
                created_at=d.created_at,
            )
            for d in detections
        ]
        self.db.add_all(rows)
        self.db.commit()
        return rows
