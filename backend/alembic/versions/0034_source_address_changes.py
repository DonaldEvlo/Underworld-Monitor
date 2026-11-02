"""Changements d'adresse des sources (repérés sur le site ou dans deepdarkCTI).

Les sites .onion déménagent (DRAGON FORCE le 2026-09-04, DARKNET ARMY le
2026-08-25, LockBit annonçant son « new blog domain »). Deux tâches
planifiées les repèrent ; cette table garde l'historique, la preuve et la
décision, et sert d'ALIAS d'hôte pour que le parser dédié suive la source.

Revision ID: 0034
Revises: 0033
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_address_changes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_url", sa.String(), nullable=False),
        sa.Column("new_url", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("parsed_victims", sa.Integer(), nullable=True),
        sa.Column("common_victims", sa.Integer(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.UniqueConstraint("source_id", "new_url", name="uq_source_address_change"),
    )
    op.create_index(
        "ix_source_address_changes_source_id", "source_address_changes", ["source_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_address_changes_source_id", "source_address_changes")
    op.drop_table("source_address_changes")
