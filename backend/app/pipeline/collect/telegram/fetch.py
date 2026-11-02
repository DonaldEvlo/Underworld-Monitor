"""Recuperation de l'apercu web public d'un canal Telegram, via Tor.

⚠️ POURQUOI L'APERCU WEB (`t.me/s/<canal>`) ET PAS LE CLIENT API (MTProto).
Le Client API (Telethon/Pyrogram) donnerait l'historique complet et les
canaux prives, mais exige un COMPTE (numero de telephone + api_id/api_hash +
session persistante). Cette identite de compte est une empreinte FIXE,
bannissable, contraire a l'esprit « rotation d'IP/UA a chaque cycle » de la
regle 3 (CONTRIBUTING.md §2). L'apercu web est un simple GET HTTP anonyme, route par
Tor exactement comme les autres collecteurs, sans aucun identifiant -- au prix
d'une seule limite : uniquement les canaux PUBLICS et leurs ~20 messages les
plus recents. C'est precisement la doctrine « fraicheur incrementale, pas
crawl historique » (meme regime que Dread, `DEFAULT_MAX_PAGES = 1`).

⚠️ CLEARNET, donc verification TLS ACTIVE. Contrairement aux fetchers .onion
(dls/fetch.py, onion_healthcheck.py) qui desactivent `verify` -- une adresse
.onion est sa propre racine de confiance --, `t.me` est un hote clearnet a
certificat CA normal : ne JAMAIS desactiver la verification ici (meme regle
que onion_healthcheck._check_one). `resolve_via_proxy=True` (socks5h) route
aussi la resolution DNS par Tor, pour ne pas fuiter `t.me` au resolveur local.
"""

from __future__ import annotations

import logging

import requests

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 60


class _TransientFetchError(RuntimeError):
    """Echec susceptible de reussir au reessai -- `with_retry` (tenacity) ne
    se declenche que sur exception, jamais sur une valeur de retour."""


@with_retry
def fetch_telegram_preview(url: str) -> str:
    """Recupere le HTML de l'apercu public d'un canal Telegram via Tor.

    ⚠️ `verify` reste a True (clearnet) -- voir docstring du module."""
    polite_delay()
    proxy = build_socks5_proxy_url(resolve_via_proxy=True)
    try:
        response = requests.get(
            url,
            proxies={"http": proxy, "https": proxy},
            headers={"User-Agent": pick_user_agent()},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise _TransientFetchError(f"{type(exc).__name__} sur {url}") from exc

    if response.status_code >= 500:
        raise _TransientFetchError(f"HTTP {response.status_code} sur {url}")
    return response.text
