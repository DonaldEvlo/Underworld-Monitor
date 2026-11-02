"""Corroboration RansomLook sur les detections et les alertes.

RansomLook surveille 77 groupes ransomware la ou nous avons 6 collecteurs
DLS dedies : croiser les deux repond a « cette victime est-elle vue par un
second observateur independant ? ».

Choix de conception : les colonnes sont NULLABLE et l'etat par defaut est
`unknown`, jamais `exclusive`. Une panne reseau de RansomLook ne doit pas
faire basculer des alertes existantes en « non corrobore » -- ce serait un
faux signal de faiblesse sur une detection parfaitement valide.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Detections -------------------------------------------------------
    # Statut par detection : c'est le grain le plus fin corroborable (un
    # domaine de victime). Indexe car l'interface filtrera dessus.
    op.add_column(
        "detections",
        sa.Column("corroboration_status", sa.String(), nullable=True),
    )
    op.add_column(
        "detections",
        sa.Column("corroborated_group", sa.String(), nullable=True),
    )
    op.add_column(
        "detections",
        sa.Column("corroborated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_detections_corroboration_status",
        "detections",
        ["corroboration_status"],
    )

    # --- Alertes ----------------------------------------------------------
    # Agregat au niveau du livrable : combien des detections de cette alerte
    # sont confirmees par un second observateur, et par quel gang.
    op.add_column(
        "alerts",
        sa.Column("corroboration_status", sa.String(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("corroborated_group", sa.String(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "corroborated_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "alerts",
        sa.Column("corroborated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "corroborated_at")
    op.drop_column("alerts", "corroborated_count")
    op.drop_column("alerts", "corroborated_group")
    op.drop_column("alerts", "corroboration_status")
    op.drop_index("ix_detections_corroboration_status", table_name="detections")
    op.drop_column("detections", "corroborated_at")
    op.drop_column("detections", "corroborated_group")
    op.drop_column("detections", "corroboration_status")
