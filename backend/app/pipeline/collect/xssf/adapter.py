import logging
from datetime import datetime

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.link_extraction import extract_mentioned_urls
from app.pipeline.collect.xssf.scraper import XssfNewsItem, fetch_xssf_news

logger = logging.getLogger(__name__)


class XssfCollector(Collector):
    """Collecteur dedie a la section News du forum XSSF (voir scraper.py).
    Un `RawDocumentContract` par actualite plutot qu'un blob unique."""

    COLLECTOR_NAME = "xssf"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        try:
            items = fetch_xssf_news(str(source.url))
        except Exception:
            # ⚠️ On journalise ET on laisse remonter : rendre `[]` faisait
            # afficher « source injoignable ou vide » alors que le motif exact
            # etait connu ici (anti-bot, demenagement, structure modifiee).
            # `collect_service` capte l'exception -- la collecte des autres
            # sources n'est pas menacee.
            logger.exception("XSSF: echec de la collecte pour %s", source.url)
            raise

        # La construction est DANS le perimetre protege : un seul item mal
        # forme (champ `null` inattendu) faisait echouer toute la source avec
        # un message opaque cote UI (« expected string or bytes-like object,
        # got 'NoneType' »), alors que les autres actualites etaient
        # exploitables. On ignore l'item fautif, on garde le reste.
        documents = []
        for item in items:
            try:
                documents.append(self._build_news_document(source, item))
            except Exception:
                logger.exception(
                    "XSSF: actualite ignoree (slug=%s) pour %s", item.slug, source.url
                )
        return documents

    def _build_news_document(
        self, source: SourceContract, item: XssfNewsItem
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {item.title}", f"Date: {item.created_at}"]
        if item.section:
            content_parts.append(f"Section: {item.section}")
        if item.hack_group:
            content_parts.append(f"Groupe: {item.hack_group}")
        if item.attack_size:
            content_parts.append(f"Taille attaque: {item.attack_size}")
        content_parts += ["", item.excerpt]

        doc_url = (
            f"{str(source.url).rstrip('/')}#{item.slug}"
            if item.slug
            else str(source.url)
        )
        mentioned_urls = extract_mentioned_urls(item.excerpt, exclude_url=doc_url)
        source_meta = {
            k: v
            for k, v in {
                "section": item.section,
                "hack_group": item.hack_group,
                "attack_size": item.attack_size,
                "slug": item.slug,
                "mentioned_urls": mentioned_urls or None,
            }.items()
            if v is not None
        }
        return self._build_document(
            source,
            doc_url,
            "\n".join(content_parts),
            title=item.title,
            published_at=_parse_iso(item.created_at),
            source_meta=source_meta or None,
        )


def _parse_iso(date_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
