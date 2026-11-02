"""Orchestration de la collecte d'une source : choix du collecteur, appel,
persistance des documents nouveaux.

Extrait de api/routers/sources.py pour etre appelable depuis deux contextes
sans duplication : le routeur API (collecte a la demande, deja en place) et
les taches Celery (collecte planifiee, voir worker/tasks/collect_tasks.py).
Conforme a CONTRIBUTING.md §3.3 -- une tache Celery doit rester un wrapper fin, la
logique metier vit ici.

Ne contient pas la logique de *choix* du collecteur (`pick_collector`, dans
`pipeline/collect/routing.py`, ou vivent tous les imports d'adaptateurs) : ce
module recoit le collecteur deja choisi, ce qui le garde testable sans monter
toute la chaine de collecte."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.contracts.source import SourceContract
from app.db.models.source import Source
from app.pipeline.collect.base import Collector
from app.repositories.document_repo import RawDocumentRepository
from app.repositories.keyword_repo import KeywordRepository
from app.repositories.source_repo import SourceRepository

logger = logging.getLogger(__name__)


@dataclass
class CollectOutcome:
    success: bool
    text: str | None = None
    error: str | None = None
    produced_count: int = 0
    saved_count: int = 0
    collector_name: str | None = None
    # Duree de cette collecte, en secondes. Renseignee meme en cas d'echec :
    # une source injoignable coute du temps (delais d'attente), et l'ignorer
    # sous-estimerait l'estimation restante.
    duration_seconds: int | None = None


def collect_source(
    collector: Collector, repo: SourceRepository, source: Source
) -> CollectOutcome:
    """Collecte une source et persiste les documents nouveaux (dedup exacte
    par content_hash, puis process/detect -- voir
    RawDocumentRepository.save_new_documents).

    Concatene le contenu de tous les documents produits (pas seulement le
    premier) pour l'apercu texte : un collecteur comme `AkiraCollector`
    renvoie un document par victime annoncee, pas un blob unique -- se limiter
    au premier ferait rater le matching de mots-cles sur tout le reste.

    N'expose jamais l'exception brute d'un collecteur a l'appelant : une source
    injoignable est un cas de fonctionnement normal (site .onion hors ligne),
    pas une erreur applicative -- elle remonte dans `error`, pas en exception."""
    contract = SourceContract.model_validate(source, from_attributes=True)
    debut = time.monotonic()

    def _duree() -> int:
        return max(0, round(time.monotonic() - debut))

    try:
        documents = collector.collect(contract)
    except Exception as exc:
        _memoriser_duree(repo, source, _duree())
        return CollectOutcome(success=False, error=str(exc), duration_seconds=_duree())
    if not documents:
        _memoriser_duree(repo, source, _duree())
        return CollectOutcome(
            success=False,
            error="Aucun contenu récupéré (source injoignable ou vide)",
            duration_seconds=_duree(),
        )

    watchlist_terms = KeywordRepository(repo.db).get_active_terms()
    saved = RawDocumentRepository(repo.db).save_new_documents(
        source.id, documents, watchlist_terms
    )
    logger.info(
        "Collecte %s: %d document(s) produits, %d nouveau(x) persiste(s)",
        source.name,
        len(documents),
        len(saved),
    )

    repo.update_last_collected(source)
    _memoriser_duree(repo, source, _duree())
    combined_text = "\n\n---\n\n".join(doc.content for doc in documents)
    return CollectOutcome(
        success=True,
        text=combined_text,
        produced_count=len(documents),
        saved_count=len(saved),
        collector_name=collector.COLLECTOR_NAME,
        duration_seconds=_duree(),
    )


def _memoriser_duree(repo: SourceRepository, source: Source, secondes: int) -> None:
    """Enregistre la duree de cette passe sur la source.

    ⚠️ Ne doit JAMAIS faire echouer la collecte : le livrable est le document
    collecte, pas la statistique. Une erreur ici est journalisee et ignoree."""
    try:
        source.last_collection_duration_seconds = secondes
        repo.db.commit()
    except Exception:
        logger.exception("Duree de collecte non enregistree pour %s", source.name)
        repo.db.rollback()
