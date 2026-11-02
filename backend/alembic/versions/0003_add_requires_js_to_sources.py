"""add requires_js to sources

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10

"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "requires_js", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "requires_js")
