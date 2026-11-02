"""Niveau de credibilite d'une alerte.

Plan de credibilite, phase 5 : un axe DISTINCT
de la gravite, qui repond a « la fuite est-elle reelle ? ». Niveaux :
confirmed / doubtful / published / claimed / not_evaluated, chacun avec sa
preuve (`credibility_evidence`). Calcule par
`pipeline/alerting/credibility.assess`, renseigne en fin de `alerts.generate`.

NULL = jamais evalue, a ne pas confondre avec `not_evaluated` (evalue, mais
sans document source).

Revision ID: 0031
Revises: 0030
"""

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("credibility_level", sa.String(), nullable=True))
    op.add_column(
        "alerts", sa.Column("credibility_evidence", sa.String(), nullable=True)
    )
    op.add_column(
        "alerts",
        sa.Column("credibility_assessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_credibility_level", "alerts", ["credibility_level"])


def downgrade() -> None:
    op.drop_index("ix_alerts_credibility_level", table_name="alerts")
    op.drop_column("alerts", "credibility_assessed_at")
    op.drop_column("alerts", "credibility_evidence")
    op.drop_column("alerts", "credibility_level")
