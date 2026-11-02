import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Keyword(Base):
    """Terme à surveiller (watchlist) : nom de domaine client, dirigeant, produit...
    Recherché (sous-chaîne, insensible à la casse) dans le texte de chaque page
    collectée — voir `app.pipeline.detect.keyword_match`."""

    __tablename__ = "keywords"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    term: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
