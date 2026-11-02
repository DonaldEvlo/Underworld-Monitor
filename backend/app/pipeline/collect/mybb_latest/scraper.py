"""Collecte du listing de sous-forums cibles (Databases, Stealer Logs,
Doxes, Combolist...) sur des forums MyBB accessibles sans compte -- couvre
DarkForums et Spear (meme moteur MyBB, meme markup, deux instances/miroirs
differents de la meme communaute de leaks).

Contrairement a BREACH FORUMS (voir breachforums_guest/, qui renvoie HTTP 403
au-dela de la page d'accueil), ces deux forums laissent l'acces invite au
listing de sous-forum ET au corps du premier post d'un fil -- verifie
manuellement avant d'ecrire ce module (voir conversation projet).

Un sous-forum a la fois (pas de flux "derniers messages" global comme
XenForo, voir xenforo_latest/) : ce module parcourt la pagination interne
d'UN sous-forum donne, avec un plafond de pages (meme principe que
xenforo_latest -- fraicheur incrementale, pas crawl historique complet)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_MAX_PAGES_SAFETY_CAP = 300
# Meme logique que xenforo_latest.DEFAULT_MAX_PAGES : fraicheur incrementale
# par cycle de collecte, pas crawl historique complet a chaque fois.
DEFAULT_MAX_PAGES = 2


@dataclass(frozen=True)
class MyBBThread:
    title: str
    thread_url: str
    author: str | None
    created_at: datetime | None
    # Corps du premier message -- None si le fetch du fil a echoue/pas tente.
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
        verify=not _is_onion(url),
    )
    response.raise_for_status()
    return response.text


# Deux formats constates selon l'instance MyBB (config d'affichage de date
# propre a chaque forum, pas standardisee) :
#   - DarkForums : "22-02-26, 10:56 AM"   (DD-MM-YY)
#   - Spear      : "06-19-2026, 03:49 PM" (MM-DD-YYYY)
# Distingues par la longueur de la 3e partie (YY vs YYYY) -- essayer les deux
# formats dans l'ordre plutot que deviner selon le site (plus robuste si un
# futur site MyBB utilise encore une autre config).
_DATE_RE = re.compile(
    r"(\d{2}-\d{2}-\d{2,4}),?\s*(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE
)
_DATE_FORMATS = ("%d-%m-%y %I:%M %p", "%m-%d-%Y %I:%M %p")


def _parse_thread_date(text: str) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    raw = f"{match.group(1)} {match.group(2)}"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _parse_thread_row(row, base_url: str) -> MyBBThread | None:
    # Le titre du fil est le premier lien "Thread-..." de la ligne qui n'est
    # pas un lien de pagination/action (?action=newpost, ?page=N).
    title_link = None
    for link in row.select('a[href*="Thread-"]'):
        href = link.get("href", "")
        if "?action=" in href or "?page=" in href:
            continue
        title_link = link
        break
    if title_link is None or not title_link.get_text(strip=True):
        return None

    author_el = row.select_one(".author a") or row.select_one(".author")
    # Classe differente selon l'instance MyBB, voir _DATE_FORMATS.
    date_el = row.select_one(".forum-display__thread-date") or row.select_one(
        ".thread_start_datetime"
    )

    return MyBBThread(
        title=title_link.get_text(strip=True),
        thread_url=urljoin(base_url, title_link["href"]),
        author=author_el.get_text(strip=True) if author_el else None,
        created_at=(
            _parse_thread_date(date_el.get_text(strip=True)) if date_el else None
        ),
    )


def parse_forum_threads(html_text: str, base_url: str) -> list[MyBBThread]:
    """Extrait les fils listes dans une page de sous-forum (`tr.inline_row`,
    markup MyBB standard). Deduplique par URL de fil (le meme fil peut
    apparaitre plusieurs fois si epingle/annonce en plus de sa position
    normale)."""
    soup = BeautifulSoup(html_text, "html.parser")
    seen_urls: set[str] = set()
    threads: list[MyBBThread] = []

    for row in soup.select("tr.inline_row"):
        thread = _parse_thread_row(row, base_url)
        if thread is None or thread.thread_url in seen_urls:
            continue
        seen_urls.add(thread.thread_url)
        threads.append(thread)

    return threads


def find_next_page_url(html_text: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    next_link = soup.select_one('a[rel="next"]')
    if next_link is None or not next_link.get("href"):
        return None
    return urljoin(base_url, next_link["href"])


def parse_first_post_body(html_text: str) -> str | None:
    """Extrait le texte du premier message d'une page de fil (`.post_body`,
    markup MyBB standard)."""
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.select_one(".post_body")
    if body is None:
        return None
    text = body.get_text(separator=" ", strip=True)
    return text or None


def fetch_thread_first_post(thread_url: str) -> str | None:
    try:
        html_text = _fetch_html(thread_url)
    except Exception:
        logger.exception("MyBB: echec recuperation du corps de %s", thread_url)
        return None
    return parse_first_post_body(html_text)


def fetch_forum_threads(
    forum_url: str,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
) -> list[MyBBThread]:
    """Parcourt un sous-forum MyBB (ex: /Forum-Databases-Removed-Content) en
    suivant la pagination jusqu'a `max_pages`. Si `fetch_bodies=True` (par
    defaut), recupere aussi le premier message de chaque fil -- le titre seul
    ne suffit pas a juger un fil ambigu (voir xenforo_latest, meme principe)."""
    threads: list[MyBBThread] = []
    seen_urls: set[str] = set()
    current_url: str | None = forum_url
    page_count = 0

    while current_url and current_url not in seen_urls:
        seen_urls.add(current_url)
        page_count += 1
        if max_pages is not None and page_count > max_pages:
            break
        if page_count > _MAX_PAGES_SAFETY_CAP:
            logger.warning(
                "MyBB: plafond de securite (%d pages) atteint", _MAX_PAGES_SAFETY_CAP
            )
            break

        try:
            html_text = _fetch_html(current_url)
        except Exception:
            logger.exception("MyBB: echec recuperation %s, arret", current_url)
            break

        threads.extend(parse_forum_threads(html_text, current_url))
        current_url = find_next_page_url(html_text, current_url)

    if fetch_bodies:
        threads = [
            (
                thread
                if thread.body is not None
                else _with_body(thread, fetch_thread_first_post(thread.thread_url))
            )
            for thread in threads
        ]

    return threads


def _with_body(thread: MyBBThread, body: str | None) -> MyBBThread:
    return MyBBThread(
        title=thread.title,
        thread_url=thread.thread_url,
        author=thread.author,
        created_at=thread.created_at,
        body=body,
    )
