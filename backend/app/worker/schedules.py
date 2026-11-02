"""Planification Celery Beat.

⚠️ LE CALENDRIER N'EST PLUS ICI. Depuis la migration 0021, il vit dans la table
`scheduled_tasks` et est lu par `worker/db_scheduler.DatabaseScheduler` : les
horaires se gerent depuis l'interface, sans toucher au code ni recreer le
service `beat`.

Ce module ne conserve que l'amorcage : au premier demarrage sur une base
vierge, il cree les entrees par defaut a partir de `.env`, pour qu'une
installation neuve tourne sans configuration manuelle.

Frequences par defaut volontairement basses : la collecte passe par Tor avec
des delais de politesse, et les sources publient quelques annonces par jour --
collecter plus souvent multiplierait les requetes sans rien apporter, ce qui
est contraire a l'OPSEC (un rythme regulier et discret attire moins
l'attention qu'un martelage).
"""

import logging

from app.core.config import settings
from app.db.models.scheduled_task import ScheduledTask
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Entrees creees UNIQUEMENT si la table est vide (voir `seed_default_schedule`).
_DEFAUTS = [
    ("Collecte des sources actives", "collect.all_active_sources", "celery"),
    ("Generation des alertes", "alerts.generate", "celery"),
    ("Collecte Dread", "collect.dread", "dread"),
    ("Verification de vivacite des liens", "links.check_corpus", "links"),
]


def seed_default_schedule() -> None:
    """Cree les entrees par defaut si la table est VIDE.

    ⚠️ Ne recree jamais une entree supprimee : la condition porte sur la table
    entiere, pas ligne par ligne. Sans cela, supprimer une collecte depuis
    l'interface la verrait reapparaitre au prochain demarrage de `beat` --
    l'utilisateur aurait raison de croire que le produit ignore ses reglages.
    """
    db = SessionLocal()
    try:
        if db.query(ScheduledTask).first() is not None:
            return
        horaires = {
            "collect.all_active_sources": (
                settings.COLLECT_SCHEDULE_MINUTE,
                settings.COLLECT_SCHEDULE_HOURS,
            ),
            "alerts.generate": (settings.ALERT_SCHEDULE_MINUTE, "*"),
            "collect.dread": (
                settings.DREAD_COLLECT_SCHEDULE_MINUTE,
                settings.DREAD_COLLECT_SCHEDULE_HOUR,
            ),
            "links.check_corpus": (
                settings.LINK_CHECK_SCHEDULE_MINUTE,
                settings.LINK_CHECK_SCHEDULE_HOUR,
            ),
        }
        for label, action, queue in _DEFAUTS:
            minute, heure = horaires[action]
            db.add(
                ScheduledTask(
                    task_name=label,
                    label=label,
                    action=action,
                    cron_minute=str(minute),
                    cron_hour=str(heure),
                    cron_day_of_week="*",
                    queue=queue,
                    enabled=True,
                )
            )
        db.commit()
        logger.info("Planification par defaut creee (%d entrees)", len(_DEFAUTS))
    except Exception:
        logger.exception("Amorcage de la planification impossible")
        db.rollback()
    finally:
        db.close()
