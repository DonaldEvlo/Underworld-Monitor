"""create alerts and alert_detections tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        # Date (sans heure) du regroupement -- une alerte par (entity_id, alert_date),
        # voir services/alert_service.py. Colonne dediee plutot que deriver de
        # created_at::date a chaque requete : indexable directement pour la
        # recherche d'idempotence.
        sa.Column("alert_date", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alerts_entity_id", "alerts", ["entity_id"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    # Une seule alerte par entite et par jour (voir alert_service.py) --
    # contrainte en base plutot que confiance seule au code applicatif.
    op.create_unique_constraint(
        "uq_alerts_entity_id_alert_date", "alerts", ["entity_id", "alert_date"]
    )

    op.create_table(
        "alert_detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id"),
            nullable=False,
        ),
        sa.Column(
            "detection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("detections.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_detections_alert_id", "alert_detections", ["alert_id"])
    # Une detection ne doit rattacher qu'une seule fois a une meme alerte
    # (l'orchestrateur peut re-scanner des detections deja rattachees lors
    # d'une re-execution le meme jour, voir alert_service.py).
    op.create_unique_constraint(
        "uq_alert_detections_alert_id_detection_id",
        "alert_detections",
        ["alert_id", "detection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_detections_alert_id", table_name="alert_detections")
    op.drop_table("alert_detections")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_entity_id", table_name="alerts")
    op.drop_table("alerts")
