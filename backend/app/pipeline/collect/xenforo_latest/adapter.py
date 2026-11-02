import logging
from datetime import datetime, timezone
from urllib.parse import urljoin

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.link_extraction import (
    extract_mentioned_urls,
    is_content_locked,
)
from app.pipeline.collect.xenforo_latest.scraper import (
    XenForoPost,
    fetch_xenforo_latest_posts,
)

logger = logging.getLogger(__name__)

# Chemin du flux "derniers messages" par hote connu -- le seul bout
# specifique a chaque site (le reste du module est generique, voir
# scraper.py). Ajouter une nouvelle source XenForo ici suffit a la brancher.
LATEST_POSTS_PATH_BY_HOST = {
    "bfdxjkv5e2z3ilrifzbnvxxvhbzsj67akjpj3zc6smzr4vv6oz565gyd.onion": "/whats-new/posts/",
    "dna777ucpo4unwxrzw5mzs4iqm5qz3uepw3k5mvwbt7tnufryvsgy5yd.onion": "/lfs/tab/?tab_id=latest_posts&page=1",
    # Nouvelle adresse DARKNET ARMY (2026-08-25). L'ancienne (dna777...) echoue
    # 3/3 essais avec renouvellement de circuit alors que celle-ci repond ;
    # les deux sont gardees, un .onion peut revenir.
    #
    # ⚠️ Le chemin DIFFERE de l'ancienne adresse : `/lfs/tab/...` repond bien
    # HTTP 200 ici mais avec **0 bloc et 0 titre** -- un blob sans la moindre
    # erreur. C'est `/whats-new/posts/` (20 fils) qu'il faut. Verifier le
    # chemin, jamais le supposer identique entre deux miroirs.
    "darknet77vonbqeatfsnawm5jtnoci5z22mxay6cizmoucgmz52mwyad.onion": "/whats-new/posts/",
}


def is_known_xenforo_url(url: str) -> bool:
    return any(host in url for host in LATEST_POSTS_PATH_BY_HOST)


def _start_url_for(source_url: str) -> str | None:
    for host, path in LATEST_POSTS_PATH_BY_HOST.items():
        if host in source_url:
            return urljoin(source_url, path)
    return None


class XenForoLatestPostsCollector(Collector):
    """Collecteur generique pour les sources XenForo connues (voir
    LATEST_POSTS_PATH_BY_HOST) : recupere le flux "derniers messages" plutot
    que de crawler chaque sous-forum individuellement -- couvre tout le forum
    en suivant simplement la pagination `rel=next`."""

    COLLECTOR_NAME = "xenforo_latest"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        start_url = _start_url_for(str(source.url))
        if start_url is None:
            logger.warning(
                "XenForo: pas de flux 'derniers messages' connu pour %s", source.url
            )
            return []

        try:
            posts = fetch_xenforo_latest_posts(start_url)
        except Exception:
            logger.exception("XenForo: echec de la collecte pour %s", source.url)
            return []

        return [self._build_post_document(source, post) for post in posts]

    def _build_post_document(
        self, source: SourceContract, post: XenForoPost
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {post.title}"]
        if post.forum_name:
            content_parts.append(f"Forum: {post.forum_name}")
        if post.timestamp:
            content_parts.append(f"Timestamp: {post.timestamp}")
        if post.body:
            content_parts.append(f"\n{post.body}")
        else:
            content_parts.append(
                "\n[corps du message non recupere -- voir le lien du fil]"
            )
        content_parts.append(f"\nLien du fil: {post.thread_url}")

        body_text = post.body or ""
        mentioned_urls = extract_mentioned_urls(body_text, exclude_url=post.thread_url)
        content_locked = is_content_locked(body_text)

        meta: dict = {}
        if post.forum_name:
            meta["forum_name"] = post.forum_name
            meta["forum_url"] = post.forum_url
        if mentioned_urls:
            meta["mentioned_urls"] = mentioned_urls
        if content_locked:
            meta["content_locked"] = True

        return self._build_document(
            source,
            post.thread_url,
            "\n".join(content_parts),
            title=post.title,
            published_at=_from_unix(post.timestamp),
            author=post.author,
            source_meta=meta or None,
        )


def _from_unix(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
