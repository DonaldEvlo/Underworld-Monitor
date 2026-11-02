"""Parsing PUR de l'apercu web public d'un canal Telegram (`t.me/s/<canal>`).

Aucun reseau ici (injecte par l'adaptateur) : ce module transforme le HTML de
l'apercu en une liste de `TelegramPost`, un par message. Testable sans Tor.

Structure verifiee en conditions reelles le 2026-09-14 (via Tor) : chaque
message est un `div.tgme_widget_message` portant `data-post="<canal>/<id>"`,
un `.tgme_widget_message_text`, une date ISO dans `.tgme_widget_message_date
time[datetime]`, et un compteur de vues `.tgme_widget_message_views`.

⚠️ LES VUES NE SONT PAS DU CONTENU. Elles augmentent a chaque consultation :
les inclure dans le texte casserait la deduplication par `content_hash` --
exactement le piege des compteurs volatils d'ORION/KRYBIT (CONTRIBUTING.md, memo
`volatile-counter-defeats-dedup`). Le scraper les expose a part ; l'adaptateur
les range dans `source_meta`, jamais dans `content`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# Hotes Telegram publics. `telegram.dog` est un miroir officiel historique.
_TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.dog"}

# Segments de tete qui ne sont PAS un nom de canal public consultable :
#   s        -> le prefixe d'apercu lui-meme (`t.me/s/<canal>`)
#   joinchat -> lien d'invitation vers un canal PRIVE (pas d'apercu public)
#   c        -> `t.me/c/<id>` = canal prive par identifiant interne
# Les liens d'invitation `t.me/+<hash>` sont ecartes par le prefixe `+`.
_RESERVED_FIRST_SEGMENTS = {"s", "joinchat", "c"}


@dataclass(frozen=True)
class TelegramPost:
    """Un message d'un canal public Telegram."""

    channel: str
    message_id: int
    url: str  # permalien public clearnet : https://t.me/<canal>/<id>
    text: str
    published_at: datetime | None = None
    author: str | None = None
    # Compteur de vues brut ("1.43M"), pour `source_meta` UNIQUEMENT --
    # jamais pour le `content` (compteur volatil, casse la dedup).
    views: str | None = None


def is_telegram_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return host in _TELEGRAM_HOSTS


def channel_from_url(url: str) -> str | None:
    """Nom du canal public depuis n'importe quelle forme d'URL Telegram, ou
    None si l'URL ne designe pas un canal public consultable.

    Gere `t.me/<canal>`, `t.me/s/<canal>`, `t.me/<canal>/123` (avec ou sans
    `@`). Ecarte les liens d'invitation (`+hash`, `joinchat`) et les canaux
    prives (`c/<id>`) : l'apercu web n'y donne pas acces."""
    if not is_telegram_url(url):
        return None
    segments = [s for s in urlparse(url).path.split("/") if s]
    if not segments:
        return None
    if segments[0] == "s":
        segments = segments[1:]
        if not segments:
            return None
    first = segments[0].lstrip("@")
    if not first or first.startswith("+") or first.lower() in _RESERVED_FIRST_SEGMENTS:
        return None
    # Nom d'utilisateur Telegram : 5-32 caracteres, alphanumeriques + `_`.
    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", first):
        return None
    return first


def preview_url(channel: str) -> str:
    """URL de l'apercu public d'un canal (celle que le fetcher recupere)."""
    return f"https://t.me/s/{channel.lstrip('@')}"


def permalink(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}"


def _parse_views(raw: str | None) -> str | None:
    """Normalise l'affichage des vues sans le convertir en nombre.

    On garde la CHAINE ("1.4M") plutot qu'un entier : c'est une metadonnee
    d'affichage, pas une mesure qui entrerait dans un calcul -- et surtout pas
    dans le `content` (volatil)."""
    if not raw:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _extract_text(message) -> str:
    """Texte du message, sauts de ligne preserves (`<br>` -> `\n`)."""
    text_el = message.select_one(".tgme_widget_message_text")
    if text_el is None:
        return ""
    for br in text_el.select("br"):
        br.replace_with("\n")
    return text_el.get_text().strip()


def _parse_datetime(message) -> datetime | None:
    time_el = message.select_one(".tgme_widget_message_date time[datetime]")
    if time_el is None:
        time_el = message.select_one("time[datetime]")
    if time_el is None:
        return None
    raw = time_el.get("datetime")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (ValueError, TypeError):
        return None


def _parse_data_post(message) -> tuple[str, int] | None:
    """`data-post="<canal>/<id>"` -> (canal, id). None si absent/malforme."""
    raw = message.get("data-post")
    if not raw or "/" not in raw:
        return None
    channel, _, tail = raw.rpartition("/")
    try:
        return channel, int(tail)
    except ValueError:
        return None


def parse_channel_messages(html: str, fallback_channel: str) -> list[TelegramPost]:
    """Extrait les messages de l'apercu d'un canal.

    ⚠️ Un message de SERVICE (arrivee, epinglage, sondage sans texte) n'a pas
    de `.tgme_widget_message_text` : il est ecarte, car il n'y a rien a passer
    a la detection. `fallback_channel` sert quand `data-post` manque."""
    soup = BeautifulSoup(html, "html.parser")
    posts: list[TelegramPost] = []
    for message in soup.select("div.tgme_widget_message"):
        text = _extract_text(message)
        if not text:
            continue
        parsed = _parse_data_post(message)
        if parsed is not None:
            channel, message_id = parsed
        else:
            channel, message_id = fallback_channel, 0
        author_el = message.select_one(
            ".tgme_widget_message_owner_name, .tgme_widget_message_author_name"
        )
        views_el = message.select_one(".tgme_widget_message_views")
        posts.append(
            TelegramPost(
                channel=channel,
                message_id=message_id,
                url=permalink(channel, message_id),
                text=text,
                published_at=_parse_datetime(message),
                author=author_el.get_text().strip() if author_el else None,
                views=_parse_views(views_el.get_text() if views_el else None),
            )
        )
    return posts
