import logging
from datetime import datetime, timezone

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.akira.scraper import AkiraLeak, fetch_akira_leaks
from app.pipeline.collect.base import Collector

logger = logging.getLogger(__name__)


class AkiraCollector(Collector):
    """Collecteur dedie au site de fuite Akira (voir scraper.py pour le detail
    de l'API interne). Un `RawDocumentContract` par victime annoncee plutot
    qu'un blob unique pour toutes les pages : chaque annonce est une unite
    d'alerte distincte, avec sa propre date et son propre contenu."""

    COLLECTOR_NAME = "akira"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        try:
            leaks = fetch_akira_leaks(str(source.url))
        except Exception:
            logger.exception("Akira: echec de la collecte pour %s", source.url)
            return []

        return [self._build_leak_document(source, leak) for leak in leaks]

    def _build_leak_document(
        self, source: SourceContract, leak: AkiraLeak
    ) -> RawDocumentContract:
        content_parts = [f"Victime: {leak.name}", f"Date: {leak.date}", "", leak.desc]
        if leak.data_link:
            # Reference textuelle uniquement -- jamais recuperee par ce module (voir scraper.py).
            content_parts.append(f"\n[indicateur, non recupere] {leak.data_link}")

        doc_url = (
            f"{str(source.url).rstrip('/')}#leak-{_slugify(leak.name)}-{leak.date}"
        )
        meta = (
            {"data_link": leak.data_link, "mentioned_urls": [leak.data_link]}
            if leak.data_link
            else None
        )
        return self._build_document(
            source,
            doc_url,
            "\n".join(content_parts),
            title=leak.name,
            published_at=_parse_date(leak.date),
            source_meta=meta,
        )


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _slugify(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:60]
