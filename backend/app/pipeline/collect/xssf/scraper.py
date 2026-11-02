"""Collecte de la section "News" du forum XSSF (forum russophone
cybersecurite/hacking).

Le site est une application Laravel + Inertia.js : contrairement au rendu
HTML classique, le contenu reel n'est pas dans des balises `<a>` mais
serialise en JSON dans l'attribut `data-page` du conteneur racine, sur CHAQUE
page HTML (pas d'appel reseau separe necessaire, contrairement a Akira ou le
JSON venait d'un endpoint distinct). Pagination Laravel standard (`?page=N`,
`meta.last_page`).

Cette section "News" documente des fuites/attaques deja publiques (ex:
annonces de dumps de donnees) -- c'est un flux d'actualites, pas les threads
de discussion du forum lui-meme (pas encore localises)."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import requests

from app.pipeline.collect.page_diagnosis import diagnostiquer_page
from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_DATA_PAGE_RE = re.compile(r'data-page="([^"]*)"')
_MAX_PAGES_SAFETY_CAP = 100

KNOWN_XSSF_HOSTS = (
    "xssfnet2env65wnrlixkn4io3gzukirz7w767gdilk64iq6dg33jwsad.onion",
    "xssfnet2env25nv16wnqn3vik4igq3igq3igq767igdik6jsad.onion",
)


@dataclass(frozen=True)
class XssfNewsItem:
    title: str
    excerpt: str
    created_at: str
    section: str | None
    hack_group: str | None
    attack_size: str | None
    slug: str | None


def is_xssf_url(url: str) -> bool:
    return any(host in url for host in KNOWN_XSSF_HOSTS)


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _is_onion(url: str) -> bool:
    return url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")


def _extract_inertia_payload(html_text: str) -> dict | None:
    match = _DATA_PAGE_RE.search(html_text)
    if not match:
        return None
    import json

    return json.loads(html.unescape(match.group(1)))


@with_retry
def _fetch_page(base_url: str, page: int) -> dict:
    polite_delay()
    session = _build_session()
    url = base_url.rstrip("/") + ("/" if page == 1 else f"/?page={page}")
    response = session.get(
        url,
        headers={"User-Agent": pick_user_agent()},
        timeout=70,
        verify=not _is_onion(
            url
        ),  # certificat auto-signe .onion, cf. onion_healthcheck.py
    )
    response.raise_for_status()
    payload = _extract_inertia_payload(response.text)
    if payload is None:
        # ⚠️ « Payload introuvable » decrit le symptome, pas la cause. Mesure du
        # 2026-09-04 : XSSF servait une page « Access Verification » avec un
        # CAPTCHA -- la source n'etait ni morte ni cassee, elle etait fermee.
        raise ValueError(diagnostiquer_page(response.text))
    return payload


def _parse_news_items(payload: dict) -> list[XssfNewsItem]:
    news = payload.get("props", {}).get("news", {})
    items = []
    for obj in news.get("data", []):
        section = obj.get("section") or {}
        items.append(
            XssfNewsItem(
                # `or ""` et non `get(..., "")` : le JSON Inertia contient des
                # `null` explicites (constate le 2026-08-21 sur `excerpt`), que
                # `get` avec defaut ne rattrape PAS -- il ne comble qu'une cle
                # absente. Un None se propageait jusqu'a
                # `extract_mentioned_urls`, qui plantait tout le collecteur
                # (TypeError sur re.finditer) alors que les autres actualites
                # etaient parfaitement exploitables.
                title=obj.get("title") or "",
                excerpt=obj.get("excerpt") or "",
                created_at=obj.get("created_at") or "",
                section=section.get("name"),
                hack_group=obj.get("hack_group"),
                attack_size=obj.get("attack_size"),
                slug=obj.get("slug"),
            )
        )
    return items


def fetch_xssf_news(base_url: str, max_pages: int | None = None) -> list[XssfNewsItem]:
    """Recupere toutes les actualites de la section News (ou seulement les
    `max_pages` premieres pages si fourni)."""
    first_payload = _fetch_page(base_url, 1)
    meta = first_payload.get("props", {}).get("news", {}).get("meta", {})
    total_pages = meta.get("last_page", 1)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)
    total_pages = min(total_pages, _MAX_PAGES_SAFETY_CAP)

    items = _parse_news_items(first_payload)
    for page_num in range(2, total_pages + 1):
        try:
            payload = _fetch_page(base_url, page_num)
        except Exception:
            logger.exception(
                "XSSF: echec recuperation page %d, arret de la pagination", page_num
            )
            break
        items.extend(_parse_news_items(payload))

    return items
