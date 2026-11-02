"""Collecteur de canaux Telegram publics, via l'apercu web (`t.me/s/<canal>`).

Un `RawDocumentContract` par MESSAGE (pas un blob par canal) : chaque annonce
est une unite de detection distincte, avec sa date et son permalien -- meme
principe que DreadCollector et RansomLookCollector.

⚠️ PERIMETRE : observation de contenu DEJA PUBLIC sur un canal public
(regle 1). Ce collecteur ne rejoint aucun canal, ne poste rien, ne pilote
aucun compte -- un simple GET HTTP anonyme route par Tor. La collecte de
canaux prives (Client API + compte) est hors perimetre tant qu'une identite
de compte persistante n'a pas ete arbitree (voir fetch.py).

⚠️ Un canal Telegram est traite comme un FORUM, pas comme un site de fuite :
un domaine qui y est cite n'est pas forcement une victime de l'auteur du
canal. Il n'est donc PAS dans `VICTIM_PUBLISHING_COLLECTORS` -- ses documents
passent par le classifieur d'annonces (leak/noise/uncertain) comme les forums.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.telegram.fetch import fetch_telegram_preview
from app.pipeline.collect.telegram.scraper import (
    TelegramPost,
    channel_from_url,
    is_telegram_url,
    parse_channel_messages,
    preview_url,
)

logger = logging.getLogger(__name__)

# Longueur max du titre derive (premiere ligne du message).
_TITLE_MAX = 120


class TelegramChannelCollector(Collector):
    """Collecte les messages recents d'un canal Telegram public.

    Le fetcher est INJECTE (defaut : `fetch_telegram_preview`, via Tor) pour
    rendre le parsing testable sans reseau -- meme patron que DlsCollector."""

    COLLECTOR_NAME = "telegram"
    COLLECTOR_VERSION = "1"

    def __init__(
        self, html_fetcher: Callable[[str], str] = fetch_telegram_preview
    ) -> None:
        self._fetch = html_fetcher

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        channel = channel_from_url(str(source.url))
        if channel is None:
            logger.warning(
                "Telegram: URL sans canal public consultable: %s "
                "(lien d'invitation ou canal prive ?)",
                source.url,
            )
            return []

        try:
            html = self._fetch(preview_url(channel))
        except Exception:
            logger.exception("Telegram: echec de la collecte pour %s", channel)
            return []

        documents: list[RawDocumentContract] = []
        for post in parse_channel_messages(html, channel):
            # Un message malforme ne doit pas perdre le canal entier
            # (patron xssf/adapter.py, CONTRIBUTING.md §8).
            try:
                documents.append(self._build_document(source, post))
            except Exception:
                logger.exception(
                    "Telegram: message ignore (%s/%s)", channel, post.message_id
                )
        return documents

    def _build_document(
        self, source: SourceContract, post: TelegramPost
    ) -> RawDocumentContract:
        first_line = post.text.strip().splitlines()[0] if post.text.strip() else ""
        title = first_line[:_TITLE_MAX] or None
        return Collector._build_document(
            self,
            source,
            url=post.url,
            # ⚠️ `content` = le TEXTE seul. Les vues (volatiles) vont dans
            # `source_meta`, jamais ici : sinon `content_hash` changerait a
            # chaque consultation et la dedup ne reconnaitrait jamais un
            # message deja vu (piege ORION/KRYBIT).
            content=post.text,
            title=title,
            published_at=post.published_at,
            author=post.author,
            source_meta={
                "channel": post.channel,
                "message_id": post.message_id,
                "views": post.views,
            },
        )


__all__ = ["TelegramChannelCollector", "is_telegram_url"]
