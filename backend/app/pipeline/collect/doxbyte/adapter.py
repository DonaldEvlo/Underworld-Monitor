import logging
from urllib.parse import urljoin

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.doxbyte.scraper import DoxBytePaste, fetch_recent_pastes
from app.pipeline.collect.link_extraction import extract_mentioned_urls

logger = logging.getLogger(__name__)

KNOWN_DOXBYTE_HOSTS = (
    "doxbyte3hunj2pi5euqhowpohjeh36mpbw5nflag4td7sd7bcrgxn6id.onion",
)


def is_known_doxbyte_url(url: str) -> bool:
    return any(host in url for host in KNOWN_DOXBYTE_HOSTS)


class DoxByteCollector(Collector):
    """Collecteur dedie a DoxByte (paste site) : liste les pastes publics
    recents via l'API JSON interne du site (voir scraper.py -- pas de rendu
    HTML/Playwright necessaire, la SPA expose une API REST simple)."""

    COLLECTOR_NAME = "doxbyte"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        if not is_known_doxbyte_url(str(source.url)):
            logger.warning("DoxByte: host non reconnu pour %s", source.url)
            return []

        try:
            pastes = fetch_recent_pastes(str(source.url))
        except Exception:
            logger.exception("DoxByte: echec de la collecte pour %s", source.url)
            return []

        return [self._build_paste_document(source, paste) for paste in pastes]

    def _build_paste_document(
        self, source: SourceContract, paste: DoxBytePaste
    ) -> RawDocumentContract:
        paste_url = urljoin(str(source.url), f"/pastes/{paste.id}")

        content_parts = [f"Titre: {paste.title}"]
        if paste.content:
            content_parts.append(f"\n{paste.content}")
        else:
            content_parts.append("\n[contenu non recupere -- voir le lien]")
        content_parts.append(f"\nLien: {paste_url}")

        body_text = paste.content or ""
        mentioned_urls = extract_mentioned_urls(body_text, exclude_url=paste_url)

        return self._build_document(
            source,
            paste_url,
            "\n".join(content_parts),
            title=paste.title,
            published_at=paste.created_at,
            author=paste.author,
            source_meta={"mentioned_urls": mentioned_urls} if mentioned_urls else None,
        )
