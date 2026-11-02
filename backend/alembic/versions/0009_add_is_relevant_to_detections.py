"""add is_relevant to detections

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-23

"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detections",
        sa.Column("is_relevant", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_detections_is_relevant", "detections", ["is_relevant"])


def downgrade() -> None:
    op.drop_index("ix_detections_is_relevant", table_name="detections")
    op.drop_column("detections", "is_relevant")
