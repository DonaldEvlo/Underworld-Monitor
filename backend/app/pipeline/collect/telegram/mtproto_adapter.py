"""Collecteur Telegram par le Client API (MTProto), avec repli sur l'apercu web.

Un `RawDocumentContract` par message, comme `TelegramChannelCollector`, et le
MEME nom de collecteur (`telegram`) : en aval, un canal reste traite comme un
FORUM (classifieur d'annonces, pas `source_publishes_victims`), quel que soit
le moyen de lecture. `source_meta["via"]` dit lequel a servi.

⚠️ REPLI SUR L'APERCU WEB si le compte n'est pas configure ou plus connecte :
une session revoquee ne doit pas faire perdre la source. Le repli est
JOURNALISE en avertissement -- sans cela, un compte banni passerait
inapercu, la collecte continuant simplement avec 20 messages au lieu de 100.

ℹ️ Passer de l'apercu web au Client API recree une fois les messages deja
vus : le texte extrait differe entre les deux lectures (mise en forme,
fichiers joints), donc le `content_hash` aussi. Attendu, pas une regression.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.telegram.adapter import TelegramChannelCollector
from app.pipeline.collect.telegram.mtproto import (
    DEFAULT_MAX_MESSAGES,
    MtprotoMessage,
    document_content,
    document_meta,
    document_title,
)
from app.pipeline.collect.telegram.mtproto_client import (
    TelegramNotAuthorized,
    TelegramNotConfigured,
    read_channel_history,
)
from app.pipeline.collect.telegram.scraper import channel_from_url

logger = logging.getLogger(__name__)

HistoryReader = Callable[[str, int], list[MtprotoMessage]]


class MtprotoChannelCollector(Collector):
    """Le lecteur d'historique et le collecteur de repli sont INJECTES : les
    tests tournent sans Telethon ni reseau (patron DlsCollector)."""

    COLLECTOR_NAME = "telegram"
    COLLECTOR_VERSION = "2-mtproto"

    def __init__(
        self,
        history_reader: HistoryReader = read_channel_history,
        fallback: Collector | None = None,
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._read = history_reader
        self._fallback = (
            fallback if fallback is not None else TelegramChannelCollector()
        )
        self._max = max_messages

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        channel = channel_from_url(str(source.url))
        if channel is None:
            logger.warning(
                "Telegram: URL sans canal public (lien d'invitation ?) : %s",
                source.url,
            )
            return []

        try:
            messages = self._read(channel, self._max)
        except (TelegramNotConfigured, TelegramNotAuthorized) as exc:
            logger.warning(
                "Telegram: Client API indisponible (%s) -- repli sur l'apercu web "
                "pour %s",
                exc,
                channel,
            )
            return self._fallback.collect(source)
        except Exception:
            # Canal prive, nom inexistant, FloodWait trop long : le canal est
            # abandonne pour ce cycle, les autres sources continuent.
            logger.exception("Telegram: echec de la lecture MTProto de %s", channel)
            return []

        documents: list[RawDocumentContract] = []
        for message in messages:
            try:
                documents.append(self._document(source, message))
            except Exception:
                logger.exception(
                    "Telegram: message ignore (%s/%s)", channel, message.message_id
                )
        return documents

    def _document(
        self, source: SourceContract, message: MtprotoMessage
    ) -> RawDocumentContract:
        return self._build_document(
            source,
            url=message.url,
            content=document_content(message),
            title=document_title(message),
            published_at=message.published_at,
            author=message.author,
            source_meta=document_meta(message),
        )
