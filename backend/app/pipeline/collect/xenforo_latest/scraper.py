"""Collecte du flux "derniers messages" des forums XenForo -- couvre TOUT le
forum (toutes les sous-sections) sans avoir a les crawler une par une.

Deux sources du projet tournent sur XenForo mais via des points d'entree
differents :
  - BFD Forum   : page native `/whats-new/posts/`
  - DARKNET ARMY: addon tiers "LFS", `/lfs/tab/?tab_id=latest_posts`

Le markup differe legerement entre les deux (classes de cellule differentes),
mais les DEUX exposent :
  - `a[data-tp-primary="on"]` pour le lien/titre du fil (fiable dans les deux cas)
  - `<link rel="next">` dans le `<head>` pour la page suivante -- ce qui rend
    la pagination generique : on suit ce lien plutot que de reconstruire une
    URL specifique a chaque addon/version.

Utilisable pour n'importe quelle autre source XenForo du projet en lui
donnant simplement son URL de depart (pas de config par site necessaire)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_MAX_PAGES_SAFETY_CAP = 300
# "Derniers messages" = fraicheur incrementale, pas crawl historique complet a
# chaque cycle -- DARKNET ARMY expose a lui seul 1633 pages de listing ; y
# aller chercher le corps de CHAQUE fil a chaque collecte serait ni poli ni
# soutenable. Ce plafond borne le cout par cycle (~20-150 fils selon le site).
DEFAULT_MAX_PAGES = 3


@dataclass(frozen=True)
class XenForoPost:
    title: str
    thread_url: str
    forum_name: str | None
    forum_url: str | None
    timestamp: int | None
    author: str | None
    # Texte du premier message du fil -- souvent l'info decisive pour trier un
    # titre ambigu ("SJ QuickView for VirtueMart" ne dit rien sur son contenu
    # reel sans le corps du post). None si le fetch a echoue ou n'a pas ete tente.
    body: str | None = None


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _is_onion(url: str) -> bool:
    return url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")


@with_retry
def _fetch_html(url: str) -> str:
    polite_delay()
    session = _build_session()
    response = session.get(
        url,
        headers={"User-Agent": pick_user_agent()},
        timeout=70,
        verify=not _is_onion(
            url
        ),  # certificat auto-signe .onion, cf. onion_healthcheck.py
    )
    response.raise_for_status()
    return response.text


def _parse_timestamp(item) -> int | None:
    # DARKNET ARMY (addon LFS) porte le timestamp directement sur l'item.
    data_date = item.get("data-date")
    if data_date and data_date.isdigit():
        return int(data_date)
    # BFD (page native `whats-new`) le porte sur un `<time>` interne.
    time_el = item.select_one("time.u-dt[data-time]")
    if time_el and time_el.get("data-time", "").isdigit():
        return int(time_el["data-time"])
    return None


def _parse_author(item) -> str | None:
    # BFD (page native) porte l'auteur en attribut sur l'item lui-meme.
    data_author = item.get("data-author")
    if data_author:
        return data_author
    # DARKNET ARMY (addon LFS) : `.username` est un <span> imbrique, pas un
    # <a> -- ".username" seul (sans restreindre au tag) couvre les deux cas.
    # Deux occurrences possibles (span externe + span interne avec data-user-id) :
    # on prend la plus profonde/specifique pour eviter de capturer le texte
    # englobant les deux si jamais ils different.
    author_el = item.select_one(".username[data-user-id]") or item.select_one(
        ".username"
    )
    return author_el.get_text(strip=True) if author_el else None


def _parse_struct_item(item, base_url: str) -> XenForoPost | None:
    title_link = item.select_one('a[data-tp-primary="on"]')
    if title_link is None or not title_link.get("href"):
        return None

    forum_link = item.select_one('a[href^="/forums/"]')

    return XenForoPost(
        title=title_link.get_text(strip=True),
        thread_url=urljoin(base_url, title_link["href"]),
        forum_name=forum_link.get_text(strip=True) if forum_link else None,
        forum_url=urljoin(base_url, forum_link["href"]) if forum_link else None,
        timestamp=_parse_timestamp(item),
        author=_parse_author(item),
    )


def parse_struct_items(html_text: str, base_url: str) -> list[XenForoPost]:
    soup = BeautifulSoup(html_text, "html.parser")
    posts = []
    for item in soup.select(".structItem"):
        post = _parse_struct_item(item, base_url)
        if post is not None:
            posts.append(post)
    return posts


def parse_first_post_body(html_text: str) -> str | None:
    """Extrait le texte du premier message d'une page de fil (`.message` +
    `.bbWrapper`, markup XenForo standard)."""
    soup = BeautifulSoup(html_text, "html.parser")
    first_message = soup.select_one(".message")
    if first_message is None:
        return None
    body = first_message.select_one(".bbWrapper")
    if body is None:
        return None
    text = body.get_text(separator=" ", strip=True)
    return text or None


def fetch_thread_first_post(thread_url: str) -> str | None:
    try:
        html_text = _fetch_html(thread_url)
    except Exception:
        logger.exception("XenForo: echec recuperation du corps de %s", thread_url)
        return None
    return parse_first_post_body(html_text)


def find_next_page_url(html_text: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    next_link = soup.select_one('link[rel="next"]') or soup.select_one(
        "a.pageNav-jump--next"
    )
    if next_link is None or not next_link.get("href"):
        return None
    return urljoin(base_url, next_link["href"])


def fetch_xenforo_latest_posts(
    start_url: str,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
) -> list[XenForoPost]:
    """Parcourt le flux "derniers messages" en suivant `rel=next` jusqu'a la
    derniere page (ou `max_pages` si fourni -- `DEFAULT_MAX_PAGES` par defaut,
    voir sa docstring). Si `fetch_bodies=True` (par defaut), recupere aussi le
    premier message de chaque fil trouve -- le titre seul ne suffit pas a un
    analyste pour juger un fil ambigu."""
    posts: list[XenForoPost] = []
    seen_urls: set[str] = set()
    current_url: str | None = start_url
    page_count = 0

    while current_url and current_url not in seen_urls:
        seen_urls.add(current_url)
        page_count += 1
        if max_pages is not None and page_count > max_pages:
            break
        if page_count > _MAX_PAGES_SAFETY_CAP:
            logger.warning(
                "XenForo latest-posts: plafond de securite (%d pages) atteint",
                _MAX_PAGES_SAFETY_CAP,
            )
            break

        try:
            html_text = _fetch_html(current_url)
        except Exception:
            logger.exception(
                "XenForo latest-posts: echec recuperation %s, arret", current_url
            )
            break

        posts.extend(parse_struct_items(html_text, current_url))
        current_url = find_next_page_url(html_text, current_url)

    if fetch_bodies:
        posts = [
            (
                post
                if post.body is not None
                else _with_body(post, fetch_thread_first_post(post.thread_url))
            )
            for post in posts
        ]

    return posts


def _with_body(post: XenForoPost, body: str | None) -> XenForoPost:
    return XenForoPost(
        title=post.title,
        thread_url=post.thread_url,
        forum_name=post.forum_name,
        forum_url=post.forum_url,
        timestamp=post.timestamp,
        author=post.author,
        body=body,
    )
