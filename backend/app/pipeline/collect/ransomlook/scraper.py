"""Collecte des annonces de victimes deja publiees sur des sites de fuite
ransomware, via l'agregateur public RansomLook (voir
https://www.ransomlook.io/doc/), plutot que de scraper chaque DLS
individuellement.

`GET /api/posts` (sans cle API, verifie en usage reel) retourne le flux des
annonces de victimes recemment decouvertes par RansomLook sur les sites de
fuite qu'il surveille -- `group_name` (le groupe ransomware), `post_title`
(la victime annoncee), `discovered` (horodatage). Il ne contient AUCUNE
adresse .onion : ce n'est pas une liste de sources a ajouter (voir
CONTRIBUTING.md §8 "APIs = enrichisseurs, pas sources" -- meme logique ici bien que
RansomLook soit traite comme un collecteur car il produit des RawDocument),
seulement des annonces deja publiques, dans le meme registre que ce que les
collecteurs dedies (Akira, XSSF...) capturent directement a la source.

IMPORTANT (regle OPSEC/ethique du projet, voir CONTRIBUTING.md §2 -- observation
uniquement) : ce module ne recupere jamais le contenu des DLS eux-memes, ni
les archives de donnees volees -- uniquement le nom du groupe et le nom de la
victime annoncee, deja publiques via RansomLook."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

RANSOMLOOK_HOST = "ransomlook.io"
_POSTS_ENDPOINT = "/api/posts"
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class RansomLookPost:
    group_name: str
    post_title: str
    discovered: str  # ISO 8601, tel que renvoye par l'API


def is_ransomlook_url(url: str) -> bool:
    return RANSOMLOOK_HOST in url


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


@with_retry
def _fetch_posts(base_url: str) -> list[dict]:
    polite_delay()
    session = _build_session()
    url = f"{base_url.rstrip('/').removesuffix('/api/posts')}{_POSTS_ENDPOINT}"
    response = session.get(
        url,
        headers={"User-Agent": pick_user_agent(), "Accept": "application/json"},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _parse_posts(payload: list[dict] | dict) -> list[RansomLookPost]:
    # L'API a evolue : elle retournait un tableau nu, elle renvoie desormais un
    # objet `{"posts": [...]}` (constate en usage reel -- le collecteur levait
    # `AttributeError: 'str' object has no attribute 'get'` en iterant sur les
    # cles du dict). Les deux formes sont acceptees pour ne pas dependre d'une
    # nouvelle evolution du cote de RansomLook.
    if isinstance(payload, dict):
        payload = payload.get("posts") or []

    posts = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        group_name = entry.get("group_name")
        post_title = entry.get("post_title")
        discovered = entry.get("discovered")
        if not group_name or not post_title or not discovered:
            continue
        posts.append(
            RansomLookPost(
                group_name=group_name, post_title=post_title, discovered=discovered
            )
        )
    return posts


def fetch_ransomlook_posts(base_url: str) -> list[RansomLookPost]:
    payload = _fetch_posts(base_url)
    return _parse_posts(payload)


def _parse_discovered(discovered: str | None) -> datetime | None:
    if not discovered:
        return None
    try:
        return datetime.fromisoformat(discovered.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
