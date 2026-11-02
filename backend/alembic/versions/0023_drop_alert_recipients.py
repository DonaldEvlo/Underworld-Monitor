"""Retrait de la notion de DESTINATAIRE d'alerte.

Decision de projet (2026-09-05) : le produit ne gere plus a qui l'alerte est
envoyee. Le livrable redevient l'alerte DANS l'outil, plus le rapport PDF que
l'analyste transmet lui-meme.

Sont retires :
  - `entity_contacts` (CERT/RSSI/DPO par organisation) ;
  - `alert_notifications` (trace des envois) ;
  - `alerts.last_notified_at`.

⚠️ Ce qui RESTE et n'a rien a voir avec les destinataires : les colonnes de
qualification et d'affectation ajoutees par la meme migration `0022`
(`assignee`, `analyst_note`, `resolution_reason`, `acknowledged_at`,
`resolved_at`). Elles portent le travail d'analyste, pas l'envoi.

⚠️ Verifie avant application : 1 contact de test, **0 envoi trace**, **0
alerte notifiee**, aucune tache planifiee utilisant `alerts.notify_pending`.
Aucune donnee reelle n'est perdue.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("alerts", "last_notified_at")
    op.drop_table("alert_notifications")
    op.drop_table("entity_contacts")


def downgrade() -> None:
    """Recree les structures vides -- pas leur contenu, qui n'existait pas."""
    op.create_table(
        "entity_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("entity_id", "email", name="uq_entity_contact_email"),
    )
    op.create_table(
        "alert_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False, server_default="email"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("sent_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "alerts",
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
