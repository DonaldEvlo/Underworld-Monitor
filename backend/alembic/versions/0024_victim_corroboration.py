"""Corroboration par VICTIME : revendications multiples, mode de
rapprochement, date d'indexation par le tiers.

Motif (mesure du 2026-09-11) : le flux RansomLook ne couvre que 30 jours et
l'index ne gardait qu'une revendication par domaine. Confrontees a
l'historique complet des gangs et par raison sociale, les victimes de nos
sites de fuite sont tres majoritairement indexees -- et plusieurs le sont par
DEUX gangs, information jusqu'ici ecrasee.

Colonnes nullables, sans valeur par defaut : NULL = pas encore confronte
selon la nouvelle methode, jamais « aucun gang ».

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detections",
        sa.Column("corroborated_groups", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "detections", sa.Column("corroboration_match", sa.String(), nullable=True)
    )
    op.add_column(
        "detections",
        sa.Column(
            "corroboration_first_seen_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "alerts", sa.Column("corroborated_groups", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "alerts",
        sa.Column(
            "corroboration_first_seen_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("alerts", "corroboration_first_seen_at")
    op.drop_column("alerts", "corroborated_groups")
    op.drop_column("detections", "corroboration_first_seen_at")
    op.drop_column("detections", "corroboration_match")
    op.drop_column("detections", "corroborated_groups")
