from __future__ import annotations

import builtins

import uuid

from sqlalchemy.orm import Session

from app.core.url_utils import normalize_url
from app.db.models.source import Source


class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> Source | None:
        return self.db.get(Source, id)

    def list(self, offset: int = 0, limit: int = 100) -> builtins.list[Source]:
        return list(
            self.db.query(Source)
            .order_by(Source.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_active(self) -> builtins.list[Source]:
        return list(self.db.query(Source).filter(Source.active.is_(True)).all())

    def find_duplicate(
        self, url: str, exclude_id: uuid.UUID | None = None
    ) -> Source | None:
        """Cherche une source existante pointant vers la meme adresse que `url`,
        au sens de `normalize_url` (insensible au schema/slash final). Utilise a
        la creation, la modification et l'import pour empecher deux sources sur
        la meme adresse (ex: DREAD enregistre en http:// et https:// separement).

        Vivait dans le routeur `sources.py` (`_find_duplicate`), deplace le
        2026-09-25."""
        target = normalize_url(url)
        for source in self.list(limit=10_000):
            if exclude_id is not None and source.id == exclude_id:
                continue
            if normalize_url(source.url) == target:
                return source
        return None

    def find_by_url_contains(self, substring: str) -> Source | None:
        return self.db.query(Source).filter(Source.url.contains(substring)).first()

    def create(self, source: Source) -> Source:
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def update(self, source: Source) -> Source:
        """Persiste les modifications faites sur une instance déjà attachée à la
        session (attributs assignés par l'appelant avant l'appel)."""
        self.db.commit()
        self.db.refresh(source)
        return source

    def update_last_collected(self, source: Source) -> Source:
        from datetime import datetime, timezone

        source.last_collected_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(source)
        return source

    def delete(self, id: uuid.UUID) -> None:
        source = self.get(id)
        if source is not None:
            self.db.delete(source)
            self.db.commit()
