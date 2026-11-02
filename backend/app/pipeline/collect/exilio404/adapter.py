import logging
from urllib.parse import urljoin

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.exilio404.scraper import Q2AQuestion, fetch_category_questions
from app.pipeline.collect.link_extraction import (
    extract_mentioned_urls,
    is_content_locked,
)

logger = logging.getLogger(__name__)

# Categorie ciblee par host connu -- Exilio404 est un forum generaliste
# (armes, drogues, conspiration...), seule "Doxxing" est dans le perimetre
# du projet (voir conversation projet : choix motive par cette categorie
# specifique, pas le forum dans son ensemble).
TARGET_CATEGORIES_BY_HOST: dict[str, list[str]] = {
    "exiliow4ctlzrvaglkgwqnpxdlvrxmdgvuy2hkbzqoziebfim6q5hwid.onion": ["doxxing"],
}


def is_known_exilio404_url(url: str) -> bool:
    return any(host in url for host in TARGET_CATEGORIES_BY_HOST)


def _target_category_urls_for(source_url: str) -> list[str]:
    for host, paths in TARGET_CATEGORIES_BY_HOST.items():
        if host in source_url:
            return [urljoin(source_url, path) for path in paths]
    return []


class Exilio404Collector(Collector):
    """Collecteur dedie a la categorie Doxxing d'Exilio404 (Question2Answer).
    Un `RawDocumentContract` par question, pas par reponse (voir scraper.py)."""

    COLLECTOR_NAME = "exilio404"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        category_urls = _target_category_urls_for(str(source.url))
        if not category_urls:
            logger.warning(
                "Exilio404: pas de categorie cible connue pour %s", source.url
            )
            return []

        documents = []
        for category_url in category_urls:
            try:
                questions = fetch_category_questions(category_url)
            except Exception:
                logger.exception(
                    "Exilio404: echec de la collecte pour %s", category_url
                )
                continue
            documents.extend(
                self._build_question_document(source, q) for q in questions
            )

        return documents

    def _build_question_document(
        self, source: SourceContract, question: Q2AQuestion
    ) -> RawDocumentContract:
        content_parts = [f"Titre: {question.title}"]
        if question.body:
            content_parts.append(f"\n{question.body}")
        else:
            content_parts.append(
                "\n[corps de la question non recupere -- voir le lien]"
            )
        content_parts.append(f"\nLien: {question.question_url}")

        body_text = question.body or ""
        mentioned_urls = extract_mentioned_urls(
            body_text, exclude_url=question.question_url
        )
        content_locked = is_content_locked(body_text)

        meta: dict = {}
        if mentioned_urls:
            meta["mentioned_urls"] = mentioned_urls
        if content_locked:
            meta["content_locked"] = True

        return self._build_document(
            source,
            question.question_url,
            "\n".join(content_parts),
            title=question.title,
            author=question.author,
            source_meta=meta or None,
        )
