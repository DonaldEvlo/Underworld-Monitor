"""Tache de collecte Dread. Wrapper fin (voir CONTRIBUTING.md §3.3) autour de
services/collect_service.py, partage avec le routeur API.

Tache SEPAREE de `collect.source` (file par defaut) a dessein, pour la meme
raison que link_tasks.py : un cycle Dread est long. Mesure du 2026-08-19 :
~34 s par corps de fil recupere (Tor + Playwright + delai de politesse), soit
~25 min pour un cycle borne a `DEFAULT_MAX_BODIES`. Le worker principal tourne
avec `worker_prefetch_multiplier=1` et ne prend qu'une tache a la fois : sur la
file par defaut, Dread bloquerait la collecte des autres sources ET l'alerting
horaire, or l'alerte est le livrable du produit (CONTRIBUTING.md §1).

C'est aussi pourquoi la source Dread ne doit PAS etre ramassee par
`collect.all_active_sources` : voir le filtre dans collect_tasks.py."""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.pipeline.collect.dread.adapter import DREAD_ONION_DOMAIN, DreadCollector
from app.repositories.source_repo import SourceRepository
from app.services.collect_service import collect_source
from app.worker.celery_app import celery_app
from app.worker.scheduled_guard import run_scheduled

logger = logging.getLogger(__name__)

# Limites propres a cette tache, plus larges que celles de l'app (30/35 min,
# calibrees pour une collecte courte). Un cycle nominal tient en ~25 min, mais
# le rendu partiel de Dread (voir scraper._fetch_rendered) peut tripler le
# nombre de requetes : sans marge, la tache serait tuee puis **rejouee**
# (`task_acks_late=True`) sans jamais aboutir, en remartelant le site a chaque
# tentative -- exactement ce que le delai de politesse cherche a eviter.
_SOFT_TIME_LIMIT_SECONDS = 75 * 60
_TIME_LIMIT_SECONDS = 85 * 60


@celery_app.task(
    name="collect.dread",
    queue="dread",
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TIME_LIMIT_SECONDS,
    # `acks_late=False` (contrairement au defaut de l'app) : les documents sont
    # persistes au fil de l'eau par le service, et la deduplication par
    # content_hash rend un rejeu inoffensif mais inutile. La prochaine
    # execution planifiee fera le travail -- mieux vaut ca qu'une boucle de
    # rejeu qui reenverrait du trafic Tor en pure perte.
    acks_late=False,
)
def collect_dread() -> dict:
    """Enveloppe planifiee : respecte la suspension eventuelle de la tache
    et enregistre son passage (voir worker/scheduled_guard.py). Le travail
    lui-meme est dans `_collect_dread`."""
    return run_scheduled("collect.dread", _collect_dread)


def _collect_dread() -> dict:
    """Collecte les fils recents des subdreads cibles et les persiste.

    Retrouve la source par son domaine onion plutot que par un id code en dur :
    l'id est propre a chaque base (dev/demo), le domaine est stable."""
    db = SessionLocal()
    try:
        repo = SourceRepository(db)
        source = repo.find_by_url_contains(DREAD_ONION_DOMAIN)
        if source is None:
            logger.warning("Collecte Dread: source introuvable en base")
            return {"success": False, "error": "source Dread introuvable"}

        outcome = collect_source(DreadCollector(), repo, source)
        logger.info(
            "Collecte Dread planifiee: success=%s produits=%d persistes=%d",
            outcome.success,
            outcome.produced_count,
            outcome.saved_count,
        )
        return {
            "success": outcome.success,
            "produced_count": outcome.produced_count,
            "saved_count": outcome.saved_count,
            "error": outcome.error,
        }
    finally:
        db.close()
