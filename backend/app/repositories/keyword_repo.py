from __future__ import annotations

import builtins

import uuid

from sqlalchemy.orm import Session

from app.db.models.keyword import Keyword


class KeywordRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> Keyword | None:
        return self.db.get(Keyword, id)

    def list(self) -> builtins.list[Keyword]:
        return list(self.db.query(Keyword).order_by(Keyword.created_at.desc()).all())

    def get_active_terms(self) -> builtins.list[str]:
        rows = self.db.query(Keyword.term).filter(Keyword.active.is_(True)).all()
        return [term for (term,) in rows]

    def create(self, keyword: Keyword) -> Keyword:
        self.db.add(keyword)
        self.db.commit()
        self.db.refresh(keyword)
        return keyword

    def update(self, keyword: Keyword) -> Keyword:
        """Persiste les modifications faites sur une instance déjà attachée à la
        session (attributs assignés par l'appelant avant l'appel)."""
        self.db.commit()
        self.db.refresh(keyword)
        return keyword

    def delete(self, id: uuid.UUID) -> None:
        keyword = self.get(id)
        if keyword is not None:
            self.db.delete(keyword)
            self.db.commit()
