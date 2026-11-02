"""Taches de collecte planifiee. Wrappers fins (voir CONTRIBUTING.md §3.3) : toute
la logique vit dans services/collect_service.py, partage avec le routeur API.

Une source par tache plutot qu'une tache unique pour tout le corpus : une
source .onion injoignable (cas frequent) ne doit pas empecher les autres
d'etre collectees, et l'echec est visible source par source dans les logs."""

from __future__ import annotations

import logging
import uuid

from app.db.session import SessionLocal
from app.repositories.source_repo import SourceRepository
from app.services.collect_service import collect_source
from app.worker.celery_app import celery_app
from app.worker.scheduled_guard import run_scheduled

logger = logging.getLogger(__name__)


def _pick_collector_for(source):
    """Import local : `pipeline/collect/routing.py` importe tous les
    adaptateurs de collecte (Playwright, Tor...), le charger au niveau module
    ferait payer cet import a toute tache Celery, meme celles qui ne collectent
    pas. (Jusqu'au 2026-09-25, cette fonction etait importee depuis le ROUTEUR
    `api/routers/sources.py` : le worker dependait de la couche HTTP.)"""
    from app.pipeline.collect.routing import pick_collector

    return pick_collector(source)


# Limites propres a la collecte d'une source, plus larges que celles de l'app
# (30/35 min). Mesure du 2026-08-21 sur cinq executions planifiees reelles :
# DARKNET ARMY (XenForo, forum tres actif) prend systematiquement 1292-1481 s,
# soit 21-25 min -- une marge de 5 min seulement avant `task_soft_time_limit`.
# Un jour un peu plus lent (circuit Tor degrade, forum charge) la ferait tuer
# puis **rejouer** (`task_acks_late=True`) sans jamais aboutir, en remartelant
# le forum a chaque tentative -- exactement ce que le delai de politesse
# cherche a eviter (voir CONTRIBUTING.md §8, meme piege que link_tasks/dread_tasks).
# 50 min laisse le double de la pire duree observee.
_SOFT_TIME_LIMIT_SECONDS = 50 * 60
_TIME_LIMIT_SECONDS = 55 * 60


@celery_app.task(
    name="collect.source",
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TIME_LIMIT_SECONDS,
)
def collect_one_source(source_id: str) -> dict:
    """Collecte une source unique. Retourne un resume serialisable (Celery
    exige du JSON) plutot que les documents eux-memes -- ils sont deja
    persistes par le service."""
    db = SessionLocal()
    try:
        repo = SourceRepository(db)
        source = repo.get(uuid.UUID(source_id))
        if source is None:
            logger.warning("Collecte planifiee: source %s introuvable", source_id)
            return {"source_id": source_id, "success": False, "error": "introuvable"}

        outcome = collect_source(_pick_collector_for(source), repo, source)
        logger.info(
            "Collecte planifiee %s: success=%s produits=%d persistes=%d",
            source.name,
            outcome.success,
            outcome.produced_count,
            outcome.saved_count,
        )
        return {
            "source_id": source_id,
            "name": source.name,
            "success": outcome.success,
            "produced_count": outcome.produced_count,
            "saved_count": outcome.saved_count,
            "error": outcome.error,
        }
    finally:
        db.close()


@celery_app.task(name="collect.all_active_sources")
def collect_all_active_sources() -> dict:
    """Enveloppe planifiee : respecte la suspension eventuelle de la tache
    et enregistre son passage (voir worker/scheduled_guard.py). Le travail
    lui-meme est dans `_collect_all_active_sources`."""
    return run_scheduled("collect.all_active_sources", _collect_all_active_sources)


def _collect_all_active_sources() -> dict:
    """Point d'entree de la collecte planifiee : programme une tache par source
    active. Ne collecte rien elle-meme -- elle repartit le travail, ce qui evite
    qu'une source lente monopolise le worker et rend chaque echec isolable."""
    from app.pipeline.collect.dread.adapter import is_dread_url

    db = SessionLocal()
    try:
        sources = SourceRepository(db).get_active()
    finally:
        db.close()

    # Dread est exclu de la file par defaut : son cycle dure ~25 min (Tor +
    # Playwright, ~34 s par corps de fil mesures le 2026-08-19) et le worker
    # principal ne prend qu'une tache a la fois -- il bloquerait la collecte
    # des autres sources ET l'alerting horaire. Il a sa propre tache sur la
    # file `dread` (voir worker/tasks/dread_tasks.py), planifiee separement.
    skipped = [s for s in sources if is_dread_url(s.url)]
    sources = [s for s in sources if not is_dread_url(s.url)]

    for source in sources:
        collect_one_source.delay(str(source.id))

    logger.info(
        "Collecte planifiee: %d source(s) active(s) programmee(s), %d sur file dediee",
        len(sources),
        len(skipped),
    )
    return {"scheduled": len(sources), "skipped_dedicated_queue": len(skipped)}


@celery_app.task(name="collect.victim_sources")
def collect_victim_sources() -> dict:
    """Collecte des seuls sites qui PUBLIENT leurs victimes (sites de fuite,
    AKIRA, RansomLook), plus frequente que la collecte generale.

    Pourquoi une tache a part : c'est la qu'une victime apparait en premier.
    A 2 passes par jour, notre date de premiere observation a 12 h de
    precision, alors que les agregateurs indexent en quelques minutes -- toute
    mesure d'avance serait biaisee contre nous par construction. Les forums
    (DARKNET ARMY ~30 min par passe) restent a 2 passes : les collecter plus
    souvent multiplierait le trafic Tor sans le meme benefice."""
    return run_scheduled("collect.victim_sources", _collect_victim_sources)


def _collect_victim_sources() -> dict:
    from app.pipeline.collect.dread.adapter import is_dread_url
    from app.pipeline.collect.routing import publishes_victims

    db = SessionLocal()
    try:
        sources = [
            s
            for s in SourceRepository(db).get_active()
            if not is_dread_url(s.url) and publishes_victims(s)
        ]
    finally:
        db.close()
    for source in sources:
        collect_one_source.delay(str(source.id))
    logger.info(
        "Collecte des sites de victimes: %d source(s) programmee(s)", len(sources)
    )
    return {"scheduled": len(sources)}
