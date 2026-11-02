"""create entities and entity_selectors tables

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-05

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("verification_method", sa.String(), nullable=True),
        sa.Column(
            "verification_status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "entity_selectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_entity_selectors_entity_id", "entity_selectors", ["entity_id"])
    op.create_index("ix_entity_selectors_type", "entity_selectors", ["type"])


def downgrade() -> None:
    op.drop_index("ix_entity_selectors_type", table_name="entity_selectors")
    op.drop_index("ix_entity_selectors_entity_id", table_name="entity_selectors")
    op.drop_table("entity_selectors")
    op.drop_table("entities")
