from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models.user import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> User | None:
        return self.db.get(User, id)

    def get_by_username(self, username: str) -> User | None:
        return self.db.query(User).filter(User.username == username).first()

    def create(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
