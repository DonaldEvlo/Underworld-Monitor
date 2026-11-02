"""Session d'un utilisateur connecté (migration 0035).

⚠️ Jusqu'au 2026-10-06, la déconnexion n'existait que dans le navigateur : le
jeton de rafraîchissement (7 jours) restait utilisable côté serveur après
« Se déconnecter », après un changement de mot de passe ou de rôle. Chaque
jeton porte désormais l'identifiant de sa session, et le serveur refuse tout
jeton dont la session est révoquée, inactive depuis trop longtemps, ou trop
ancienne.

Minimisation : ni adresse IP ni navigateur ne sont conservés — seulement ce
qu'il faut pour décider si la session vit encore.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Dernière requête authentifiée (mise à jour au plus toutes les 30 s).
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "logout" | "idle" | "expired" | "password_changed" | "role_changed" |
    # "deactivated"
    revoked_reason: Mapped[str | None] = mapped_column(String)
