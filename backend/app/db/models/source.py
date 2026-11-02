import uuid
from datetime import datetime

from sqlalchemy import Integer, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_js: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Duree de la DERNIERE collecte, en secondes (migration 0019). Sert a
    # estimer le temps restant pendant une collecte groupee.
    #
    # ⚠️ Derniere valeur et non moyenne : sur .onion les durees varient
    # fortement d'une passe a l'autre (DARKNET ARMY entre 1292 et 1481 s). Une
    # moyenne lissee masquerait cette variabilite ; une derniere mesure se lit
    # pour ce qu'elle est, un ordre de grandeur.
    last_collection_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
