import logging

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.breachforums_guest.scraper import (
    ThreadPreview,
    fetch_homepage_threads,
)

logger = logging.getLogger(__name__)


class BreachForumsGuestCollector(Collector):
    """Collecteur limite a la page d'accueil (acces invite) -- voir scraper.py
    pour le detail du mur d'authentification qui empeche d'aller plus loin."""

    COLLECTOR_NAME = "breachforums_guest"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        previews = fetch_homepage_threads(str(source.url))
        return [self._build_preview_document(source, preview) for preview in previews]

    def _build_preview_document(
        self, source: SourceContract, preview: ThreadPreview
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {preview.title}"]
        if preview.author:
            content_parts.append(f"Auteur: {preview.author}")
        if preview.last_post_label:
            content_parts.append(f"Dernier message: {preview.last_post_label}")
        content_parts.append(
            "\n[apercu invite uniquement -- contenu du post non accessible sans compte]"
        )

        # published_at volontairement absent : la source n'expose qu'un texte
        # relatif ("32 minutes ago"), pas d'horodatage absolu fiable a parser.
        return self._build_document(
            source,
            preview.thread_url,
            "\n".join(content_parts),
            title=preview.title,
            author=preview.author,
            source_meta=(
                {"last_post_label": preview.last_post_label}
                if preview.last_post_label
                else None
            ),
        )
