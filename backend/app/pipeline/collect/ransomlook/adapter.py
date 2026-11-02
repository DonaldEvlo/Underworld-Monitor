import logging

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.ransomlook.scraper import (
    RansomLookPost,
    _parse_discovered,
    fetch_ransomlook_posts,
)

logger = logging.getLogger(__name__)


class RansomLookCollector(Collector):
    """Collecteur dedie a l'agregateur RansomLook (voir scraper.py). Un
    `RawDocumentContract` par annonce de victime plutot qu'un blob unique --
    meme principe que AkiraCollector : chaque annonce est une unite d'alerte
    distincte, avec sa propre date."""

    COLLECTOR_NAME = "ransomlook"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        try:
            posts = fetch_ransomlook_posts(str(source.url))
        except Exception:
            logger.exception("RansomLook: echec de la collecte pour %s", source.url)
            return []

        return [self._build_post_document(source, post) for post in posts]

    def _build_post_document(
        self, source: SourceContract, post: RansomLookPost
    ) -> RawDocumentContract:
        content = (
            f"Groupe: {post.group_name}\n"
            f"Victime annoncee: {post.post_title}\n"
            f"Decouvert le: {post.discovered}"
        )
        doc_url = f"{str(source.url).rstrip('/')}#{post.group_name}-{_slugify(post.post_title)}"
        return self._build_document(
            source,
            doc_url,
            content,
            title=post.post_title,
            published_at=_parse_discovered(post.discovered),
            source_meta={"group_name": post.group_name},
        )


def _slugify(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:60]
