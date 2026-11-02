"""create detections table

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-21

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_documents.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("value_masked", sa.String(), nullable=False),
        sa.Column("value_hash", sa.String(), nullable=False),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_detections_document_id", "detections", ["document_id"])
    op.create_index("ix_detections_type", "detections", ["type"])
    op.create_index("ix_detections_value_hash", "detections", ["value_hash"])


def downgrade() -> None:
    op.drop_index("ix_detections_value_hash", table_name="detections")
    op.drop_index("ix_detections_type", table_name="detections")
    op.drop_index("ix_detections_document_id", table_name="detections")
    op.drop_table("detections")
