"""Changement d'adresse d'une source (migration 0034).

Une ligne par (source, nouvelle adresse) repérée : sur le site lui-même (avis
de migration, annonce d'un nouveau domaine) ou dans les listes deepdarkCTI.
`applied` = la source a basculé ; `pending` = repérée mais pas prouvée (à
examiner) ; `rejected` = écartée par un analyste, plus jamais reproposée.

⚠️ Une ligne `applied` est aussi un ALIAS d'hôte : nos parsers sont choisis
sur l'hôte de l'adresse, et sans cet alias une source déménagée retomberait en
silence sur le collecteur générique (piège DARKNET ARMY / DRAGON FORCE).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceAddressChange(Base):
    __tablename__ = "source_address_changes"
    __table_args__ = (
        UniqueConstraint("source_id", "new_url", name="uq_source_address_change"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_url: Mapped[str] = mapped_column(String, nullable=False)
    new_url: Mapped[str] = mapped_column(String, nullable=False)
    # "site" (le site l'annonce) | "deepdarkcti" (liste fastfire/deepdarkCTI)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    # "applied" | "pending" | "rejected"
    status: Mapped[str] = mapped_column(String, nullable=False)
    # Ce qui a fait repérer l'adresse (titre de l'avis, ligne de la liste).
    evidence: Mapped[str | None] = mapped_column(Text)
    # Pourquoi elle a été appliquée ou laissée en attente.
    reason: Mapped[str | None] = mapped_column(Text)
    # Preuve « même site » : victimes lues à la nouvelle adresse, et combien
    # sont déjà connues de nous pour cette source.
    parsed_victims: Mapped[int | None] = mapped_column(Integer)
    common_victims: Mapped[int | None] = mapped_column(Integer)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String)
