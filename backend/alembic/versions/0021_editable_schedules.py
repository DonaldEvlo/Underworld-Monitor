"""Planification MODIFIABLE : horaires geres depuis l'interface.

Jusqu'ici Celery Beat lisait son calendrier au demarrage depuis
`worker/schedules.py`, alimente par `.env` : on pouvait suspendre une tache,
jamais changer son horaire ni en ajouter une. Cette migration fait de la table
la SOURCE DE VERITE, lue par un ordonnanceur maison
(`worker/db_scheduler.py`).

Ce que cela permet : plusieurs moments de collecte par jour, un horaire par
entree, l'ajout et la suppression -- sans toucher au code ni recreer `beat`.

⚠️ `action` est contrainte a une LISTE BLANCHE (voir
services/scheduled_task_service.KNOWN_ACTIONS). Laisser l'interface nommer une
tache Celery arbitraire reviendrait a offrir l'execution de code a distance :
n'importe quelle tache enregistree deviendrait declenchable par un utilisateur
authentifie. Le champ designe donc une action prevue, pas un nom libre.

⚠️ `task_name` change de sens : il devient une ETIQUETTE lisible et unique
(« Collecte du matin »), l'action reelle passant dans `action`. Les lignes
existantes sont converties en consequence.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_tasks", sa.Column("action", sa.String(), nullable=True))
    op.add_column("scheduled_tasks", sa.Column("label", sa.String(), nullable=True))
    # Champs crontab, stockes en texte comme Celery les accepte : "6,18",
    # "*/15", "*". Les garder tels quels evite de reinventer un analyseur et
    # laisse passer les formes que Celery sait deja lire.
    op.add_column(
        "scheduled_tasks",
        sa.Column("cron_minute", sa.String(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column("cron_hour", sa.String(), nullable=False, server_default="*"),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column("cron_day_of_week", sa.String(), nullable=False, server_default="*"),
    )
    op.add_column(
        "scheduled_tasks",
        sa.Column("queue", sa.String(), nullable=False, server_default="celery"),
    )

    # Les lignes existantes portaient le nom Celery dans `task_name` : on le
    # recopie dans `action` et on repart des horaires qui etaient en dur.
    op.execute("UPDATE scheduled_tasks SET action = task_name WHERE action IS NULL")
    op.execute("UPDATE scheduled_tasks SET label = task_name WHERE label IS NULL")
    op.execute(
        "UPDATE scheduled_tasks SET cron_hour = '6,18', cron_minute = '17' "
        "WHERE action = 'collect.all_active_sources'"
    )
    op.execute(
        "UPDATE scheduled_tasks SET cron_hour = '*', cron_minute = '7' "
        "WHERE action = 'alerts.generate'"
    )
    op.execute(
        "UPDATE scheduled_tasks SET cron_hour = '13', cron_minute = '23', "
        "queue = 'dread' WHERE action = 'collect.dread'"
    )
    op.execute(
        "UPDATE scheduled_tasks SET cron_hour = '9', cron_minute = '37', "
        "queue = 'links' WHERE action = 'links.check_corpus'"
    )

    op.alter_column("scheduled_tasks", "action", nullable=False)
    op.alter_column("scheduled_tasks", "label", nullable=False)
    op.create_index("ix_scheduled_tasks_action", "scheduled_tasks", ["action"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_action", table_name="scheduled_tasks")
    for colonne in (
        "queue",
        "cron_day_of_week",
        "cron_hour",
        "cron_minute",
        "label",
        "action",
    ):
        op.drop_column("scheduled_tasks", colonne)
