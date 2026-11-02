"""Tache de verification de vivacite des liens. Wrapper fin (voir CONTRIBUTING.md
§3.3) autour de services/link_health_service.py, partage avec le routeur API.

Tache SEPAREE de la collecte a dessein : pipeline/collect/link_extraction.py
est passif par conception (il extrait des URLs, il n'en requete jamais aucune).
Greffer la verification dans le collecteur en ferait un crawler recursif, ce
que ce module refuse explicitement. Une passe distincte sur le corpus deja
collecte donne le meme resultat sans changer la nature de la collecte."""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.services.link_health_service import check_corpus_links
from app.worker.celery_app import celery_app
from app.worker.scheduled_guard import run_scheduled

logger = logging.getLogger(__name__)


# Limites propres a cette tache, plus larges que celles de l'app (30/35 min,
# calibrees pour la collecte) : une passe complete peut legitimement durer plus
# longtemps -- 152 hotes x (temps de reponse + delai de politesse 3-9s), et
# jusqu'a 45s par hote injoignable (timeout Tor). Pire cas mesure : ~130 min.
#
# Sans ces limites dediees, la tache depassait `task_time_limit` (35 min) et
# etait tuee puis **rejouee** (`task_acks_late=True`) sans jamais aboutir --
# en remartelant les memes hotes a chaque tentative, exactement ce que le
# delai de politesse cherche a eviter.
#
# `acks_late=False` ici (contrairement au defaut de l'app) : cette tache ne
# persiste rien et est purement observationnelle. La rejouer apres un crash
# n'a aucune valeur -- la prochaine execution planifiee fera le travail --
# alors qu'une boucle de rejeu enverrait du trafic en pure perte.
_SOFT_TIME_LIMIT_SECONDS = 150 * 60
_TIME_LIMIT_SECONDS = 160 * 60


@celery_app.task(
    name="links.check_corpus",
    # File dediee (voir docker-compose.yml, service `worker-links`) : cette
    # tache est longue (jusqu'a ~2h) et le worker principal ne prend qu'une
    # tache a la fois (`worker_prefetch_multiplier=1`). Sur la file par defaut,
    # elle bloquerait la collecte ET l'alerting horaire -- constate en usage
    # reel : aucune execution de `alerts.generate` pendant qu'elle tournait,
    # alors que l'alerte est precisement le livrable du produit (CONTRIBUTING.md §1).
    queue="links",
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TIME_LIMIT_SECONDS,
    acks_late=False,
)
def check_corpus_links_task() -> dict:
    """Enveloppe planifiee : respecte la suspension eventuelle de la tache
    et enregistre son passage (voir worker/scheduled_guard.py). Le travail
    lui-meme est dans `_check_corpus_links_task`."""
    return run_scheduled("links.check_corpus", _check_corpus_links_task)


def _check_corpus_links_task() -> dict:
    """Verifie les liens mentionnes dans le corpus et journalise le bilan.

    Ne persiste rien (voir link_health_service.py) : la valeur est dans le
    bilan agrege, visible dans les logs du worker et via l'API. Retourne des
    comptages, jamais le detail des metadonnees de liens tiers."""
    db = SessionLocal()
    try:
        report = check_corpus_links(db)
        logger.info(
            "Verification planifiee des liens: %d hote(s) verifie(s), statuts=%s",
            report.hosts_checked,
            report.counts_by_status,
        )
        return {
            "documents_scanned": report.documents_scanned,
            "documents_with_links": report.documents_with_links,
            "hosts_checked": report.hosts_checked,
            "counts_by_status": report.counts_by_status,
            "alive_ratio": report.alive_ratio,
        }
    finally:
        db.close()
