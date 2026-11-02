import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Entity(Base):
    """Une entite surveillee, generique (voir CONTRIBUTING.md §1 : jamais de nom
    d'organisation en dur dans le code). Voir contracts/entity.py pour le
    contrat Pydantic correspondant."""

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    verification_method: Mapped[str | None] = mapped_column(String)
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Migration 0033 : une filiale pointe vers son groupe (UN niveau, contrôlé
    # par services/entity_service). Pays (ISO 3166 alpha-2) et secteur
    # (vocabulaire `activity` de ransomware.live) DÉCLARÉS par l'analyste :
    # ils priment sur ceux d'un tiers pour les alertes de l'organisation.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), index=True
    )
    country: Mapped[str | None] = mapped_column(String(2))
    sector: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    selectors: Mapped[list["EntitySelector"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntitySelector(Base):
    """Un critere de rattachement d'une detection a une entite (voir
    contracts/entity.py -- EntitySelector). Table liee plutot que JSON sur
    `entities` : coherent avec le reste du schema (detections->raw_documents
    est deja une FK, pas un champ serialise) et permet d'indexer/filtrer par
    type+value cote SQL."""

    __tablename__ = "entity_selectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    entity: Mapped[Entity] = relationship(back_populates="selectors")
