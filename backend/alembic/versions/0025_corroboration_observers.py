"""Second observateur de corroboration : QUELS agregateurs ont vu la victime.

Motif (2026-09-15) : ransomware.live rejoint RansomLook comme observateur.
Les deux lisent le meme DLS (non independants), mais leur UNION augmente la
couverture -- APT73/CMD/PEAR, ignores de RansomLook, passent de 0 % a
jusqu'a 94 % (mesure du 2026-09-14). On enregistre desormais QUELS observateurs
ont vu chaque victime, pour ne pas confondre observateur et gang, et pour que
« exclusive » signifie « aucun observateur », pas « absent de RansomLook ».

Colonnes JSONB nullables, sans defaut : NULL = pas encore confronte selon la
nouvelle methode, jamais « aucun observateur ».

Revision ID: 0025
Revises: 0024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detections",
        sa.Column("corroboration_observers", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("corroboration_observers", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "corroboration_observers")
    op.drop_column("detections", "corroboration_observers")
