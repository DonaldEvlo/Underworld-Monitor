"""create raw_documents table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("collector", sa.String(), nullable=False),
        sa.Column("collector_version", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("source_meta", postgresql.JSONB(), nullable=True),
        sa.Column("simhash", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column(
            "is_duplicate", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_raw_documents_source_id", "raw_documents", ["source_id"])
    op.create_index("ix_raw_documents_content_hash", "raw_documents", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_raw_documents_content_hash", table_name="raw_documents")
    op.drop_index("ix_raw_documents_source_id", table_name="raw_documents")
    op.drop_table("raw_documents")
