"""Tâches de repérage des changements d'adresse des sources. Wrappers fins
(CONTRIBUTING.md §3.3) autour de services/source_address_service.py.

File `links` (service `worker-links`) : une passe sur les sites lit la page
de chaque source active via Tor, avec délais de politesse — plusieurs
minutes. Sur la file par défaut elle retarderait la collecte et l'alerting
horaire (même raisonnement que `links.check_corpus`).
"""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.services.source_address_service import (
    verifier_depuis_deepdarkcti,
    verifier_depuis_les_sites,
)
from app.worker.celery_app import celery_app
from app.worker.scheduled_guard import run_scheduled

logger = logging.getLogger(__name__)

# ~25 sources x (délai de politesse + jusqu'à 3 candidates) : large marge.
_SOFT_TIME_LIMIT_SECONDS = 60 * 60
_TIME_LIMIT_SECONDS = 65 * 60


def _passe(fonction) -> dict:
    db = SessionLocal()
    try:
        bilan = fonction(db)
        logger.info("Changements d'adresse : %s", bilan)
        return bilan
    finally:
        db.close()


@celery_app.task(
    name="sources.check_addresses_sites",
    queue="links",
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TIME_LIMIT_SECONDS,
    # Purement observationnelle hors bascule prouvée : la rejouer après un
    # crash n'apporte rien, la passe suivante fera le travail.
    acks_late=False,
)
def check_addresses_sites_task() -> dict:
    return run_scheduled(
        "sources.check_addresses_sites", lambda: _passe(verifier_depuis_les_sites)
    )


@celery_app.task(
    name="sources.check_addresses_deepdarkcti",
    queue="links",
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TIME_LIMIT_SECONDS,
    acks_late=False,
)
def check_addresses_deepdarkcti_task() -> dict:
    return run_scheduled(
        "sources.check_addresses_deepdarkcti",
        lambda: _passe(verifier_depuis_deepdarkcti),
    )
