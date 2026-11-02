"""Rappel explicite sur une alerte existante.

Complement du dedoublonnage par victime (voir alert_repo.alerted_victims) :
une organisation deja signalee ne redeclenche plus d'alerte, meme redetectee
ailleurs. Il fallait donc un moyen ASSUME de se faire re-solliciter.

⚠️ Un rappel ne cree PAS d'alerte. Il marque l'alerte existante et la remet en
`open`. Creer une seconde alerte reintroduirait exactement le doublon que le
dedoublonnage vient de supprimer -- le rappel serait alors une regression
deguisee en fonctionnalite.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts", sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "alerts",
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("alerts", "reminder_count")
    op.drop_column("alerts", "reminded_at")
