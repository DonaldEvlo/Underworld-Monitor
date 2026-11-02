"""Lien justificatif de la corroboration.

Une corroboration sans preuve consultable est une affirmation. On persiste
donc l'URL publique RansomLook (`/group/<gang>`), verifiee le 2026-08-26 :
les victimes y figurent bien.

Complementaire de l'URL deja stockee sur `raw_documents` (le .onion du DLS,
qui exige Tor) : l'une prouve ce que NOUS avons lu, l'autre ce qu'un
observateur independant publie en clearnet.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detections",
        sa.Column("corroboration_evidence_url", sa.String(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("corroboration_evidence_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "corroboration_evidence_url")
    op.drop_column("detections", "corroboration_evidence_url")
