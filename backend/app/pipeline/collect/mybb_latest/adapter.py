import logging
from urllib.parse import urljoin

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.link_extraction import (
    extract_mentioned_urls,
    is_content_locked,
)
from app.pipeline.collect.mybb_latest.scraper import MyBBThread, fetch_forum_threads

logger = logging.getLogger(__name__)

# Sous-forums cibles par host connu -- les seuls a valeur pour la detection
# (Databases/StealerLogs/Doxes/Combolist), pas tout le forum (qui contient
# aussi des sections generalistes hors perimetre, voir conversation projet
# sur le choix de ces deux forums). Verifie manuellement avant d'ajouter un
# nouveau host : chaque forum MyBB nomme ses sous-forums differemment.
TARGET_FORUMS_BY_HOST: dict[str, list[str]] = {
    "darkfoxaqhfpxkrbt7vxns2z2u2k72sgmqbzeorupaiottw3ecm2wgyd.onion": [
        "Forum-Databases-Removed-Content",
        "Forum-StealerLogs-Removed-Content",
        "Forum-Combolist-Removed-Content",
        "Forum-Doxes-Removed-Content",
    ],
    "spear4h2potiyk43oilufhuq2jqbioyaizcs7xttlyw75s5ykwxpxlid.onion": [
        "Forum-Databases",
        "Forum-Stealer-Logs",
        "Forum-Doxes",
    ],
}


def is_known_mybb_url(url: str) -> bool:
    return any(host in url for host in TARGET_FORUMS_BY_HOST)


def _target_forum_urls_for(source_url: str) -> list[str]:
    for host, paths in TARGET_FORUMS_BY_HOST.items():
        if host in source_url:
            return [urljoin(source_url, path) for path in paths]
    return []


class MyBBLatestCollector(Collector):
    """Collecteur generique pour les forums MyBB connus (voir
    TARGET_FORUMS_BY_HOST) : parcourt chaque sous-forum cible listes pour ce
    host (Databases, StealerLogs, Doxes, Combolist...), pas tout le forum."""

    COLLECTOR_NAME = "mybb_latest"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        forum_urls = _target_forum_urls_for(str(source.url))
        if not forum_urls:
            logger.warning("MyBB: pas de sous-forum cible connu pour %s", source.url)
            return []

        documents = []
        for forum_url in forum_urls:
            try:
                threads = fetch_forum_threads(forum_url)
            except Exception:
                logger.exception("MyBB: echec de la collecte pour %s", forum_url)
                continue
            documents.extend(
                self._build_thread_document(source, thread) for thread in threads
            )

        return documents

    def _build_thread_document(
        self, source: SourceContract, thread: MyBBThread
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {thread.title}"]
        if thread.body:
            content_parts.append(f"\n{thread.body}")
        else:
            content_parts.append(
                "\n[corps du message non recupere -- voir le lien du fil]"
            )
        content_parts.append(f"\nLien du fil: {thread.thread_url}")

        body_text = thread.body or ""
        mentioned_urls = extract_mentioned_urls(
            body_text, exclude_url=thread.thread_url
        )
        content_locked = is_content_locked(body_text)

        meta: dict = {}
        if mentioned_urls:
            meta["mentioned_urls"] = mentioned_urls
        if content_locked:
            meta["content_locked"] = True

        return self._build_document(
            source,
            thread.thread_url,
            "\n".join(content_parts),
            title=thread.title,
            published_at=thread.created_at,
            author=thread.author,
            source_meta=meta or None,
        )
