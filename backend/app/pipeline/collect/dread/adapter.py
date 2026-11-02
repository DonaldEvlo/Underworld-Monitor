import logging

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.dread.scraper import (
    DEFAULT_MAX_BODIES,
    DEFAULT_SUBDREADS,
    DreadThread,
    fetch_dread_threads,
)
from app.pipeline.collect.link_extraction import (
    extract_mentioned_urls,
    is_content_locked,
)

logger = logging.getLogger(__name__)

DREAD_ONION_DOMAIN = "dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion"

# Budget de corps pour une collecte DECLENCHEE A LA MAIN (bouton « Collecter
# tout », POST /collect). Mesure du 2026-08-20 : ~15 s par corps, donc le
# budget planifie (100) demande ~24 min -- acceptable la nuit, pas devant un
# analyste qui attend une reponse, d'autant qu'il monopolise l'un des 5 workers
# du batch pendant que les autres sources rendent en ~1 min.
# 20 corps ~= 5-6 min : la source est reellement collectee (listings complets
# des 8 subdreads + les 20 fils les plus recents enrichis), le cycle complet
# reste celui planifie quotidiennement.
INTERACTIVE_MAX_BODIES = 20


def is_dread_url(url: str) -> bool:
    return DREAD_ONION_DOMAIN in url


class DreadCollector(Collector):
    """Collecteur des fils recents de subdreads cibles sur Dread.

    Un `RawDocumentContract` par fil (pas un blob par subdread) : chaque
    annonce est une unite d'alerte distincte avec sa propre date et son propre
    auteur -- meme principe que RansomLookCollector et MyBBLatestCollector.

    A ne pas confondre avec `dread/search.py` : celui-la fait une recherche par
    mots-cles a la demande dont les resultats vivent en Redis (TTL 2 h) sans
    jamais etre persistes. Les deux coexistent et se completent -- la recherche
    repond a "ou parle-t-on de ce terme ?", ce collecteur alimente le pipeline
    de detection en continu."""

    COLLECTOR_NAME = "dread"
    COLLECTOR_VERSION = "1"

    def __init__(
        self,
        subdreads: tuple[str, ...] = DEFAULT_SUBDREADS,
        max_bodies: int | None = DEFAULT_MAX_BODIES,
    ) -> None:
        self._subdreads = subdreads
        self._max_bodies = max_bodies

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        try:
            threads = fetch_dread_threads(
                str(source.url), self._subdreads, max_bodies=self._max_bodies
            )
        except Exception:
            logger.exception("Dread: echec de la collecte pour %s", source.url)
            return []

        return [self._build_thread_document(source, thread) for thread in threads]

    def _build_thread_document(
        self, source: SourceContract, thread: DreadThread
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {thread.title}"]
        if thread.subdread:
            content_parts.append(f"Subdread: /d/{thread.subdread}")
        if thread.body:
            content_parts.append(f"\n{thread.body}")
        else:
            content_parts.append(
                "\n[corps du message non recupere -- voir le lien du fil]"
            )
        content_parts.append(f"\nLien du fil: {thread.thread_url}")

        body_text = thread.body or ""
        # `link_extraction` est PASSIF par conception : il extrait les URLs
        # mentionnees sans jamais les requeter (sinon le collecteur devient un
        # crawler recursif). La verification de vivacite est une passe separee
        # (`enrich/link_health.py`) -- voir CONTRIBUTING.md §8.
        mentioned_urls = extract_mentioned_urls(
            body_text, exclude_url=thread.thread_url
        )
        content_locked = is_content_locked(body_text)

        meta: dict = {}
        if thread.subdread:
            meta["subdread"] = thread.subdread
        if thread.comment_count is not None:
            meta["comment_count"] = thread.comment_count
        if mentioned_urls:
            meta["mentioned_urls"] = mentioned_urls
        if content_locked:
            meta["content_locked"] = True

        return self._build_document(
            source,
            thread.thread_url,
            "\n".join(content_parts),
            title=thread.title,
            published_at=thread.published_at,
            author=thread.author,
            source_meta=meta or None,
        )
