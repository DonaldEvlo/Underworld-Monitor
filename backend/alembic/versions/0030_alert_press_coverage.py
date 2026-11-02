"""Confirmation d'une alerte par la presse.

Premier signal de CREDIBILITE (phase 1 du plan de credibilite) :
un article de presse ou une declaration officielle, indexe par ransomware.live
pour la victime. C'est la seule preuve du projet qui ne vienne ni du gang, ni
d'un agregateur lisant le meme site que nous.

Mesure du 2026-09-24 : 409 victimes sur 8 184 (5 %) chez les 14 gangs suivis,
1 alerte sur 30 (Institution Exemple du Senegal, article du Quotidien).

`press_confirmed_at` date la PREMIERE observation de la confirmation, pas
l'article : ransomware.live ne date pas ses entrees de presse.

Revision ID: 0030
Revises: 0029
"""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("press_source_url", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("press_evidence_url", sa.String(), nullable=True))
    op.add_column(
        "alerts",
        sa.Column("press_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "press_confirmed_at")
    op.drop_column("alerts", "press_evidence_url")
    op.drop_column("alerts", "press_source_url")
