import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # `analyst` | `admin` | `viewer` -- voir core/roles.py, qui porte la
    # doctrine. ⚠️ DEFAUT `analyst`, jamais `admin` : un compte cree sans
    # precision ne doit pas pouvoir supprimer une source. Une valeur inconnue
    # est ramenee au role le MOINS puissant par `role_de()`, pas a l'admin.
    role: Mapped[str] = mapped_column(String, nullable=False, default="analyst")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
