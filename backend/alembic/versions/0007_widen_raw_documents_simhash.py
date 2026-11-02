"""widen raw_documents.simhash to bigint

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-21

"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # L'empreinte SimHash (voir pipeline/process/dedup.py) tient sur 63 bits :
    # un integer (32 bits) deborderait.
    op.alter_column("raw_documents", "simhash", type_=sa.BigInteger())


def downgrade() -> None:
    op.alter_column("raw_documents", "simhash", type_=sa.Integer())
