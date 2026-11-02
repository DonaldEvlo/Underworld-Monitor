"""Etat des taches planifiees : activation et dernier passage.

La page Collecte permettait de declencher une collecte a la main, mais rien ne
montrait ce qui tourne AUTOMATIQUEMENT : ni quelles taches sont planifiees, ni
quand elles sont passees, ni comment les suspendre.

⚠️ Ce que cette table ne fait PAS : changer les HORAIRES. Celery Beat lit son
calendrier au demarrage depuis `worker/schedules.py`, alimente par `.env` --
modifier une heure exige toujours de recreer le service `beat`. L'interface
doit le dire plutot que de laisser croire le contraire.

Ce qui devient possible a chaud, en revanche : suspendre une tache. Beat la
declenche toujours, mais la tache verifie son drapeau et se retire
immediatement. C'est volontairement ce sens-la -- il ne demande aucune
reconfiguration de Beat et reste vrai meme si Beat est relance.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        # Nom Celery de la tache (ex: "collect.all_active_sources"), qui fait
        # le lien avec `worker/schedules.py`.
        sa.Column("task_name", sa.String(), nullable=False, unique=True),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        # "success" | "error" | "skipped" -- `skipped` distingue une tache
        # suspendue d'une tache en echec, deux situations qu'un simple booleen
        # confondrait.
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("last_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("last_detail", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_tasks")
