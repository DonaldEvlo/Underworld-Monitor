"""Collecte limitee a la page d'accueil de BREACH FORUMS (MyBB), en tant
qu'invite (pas de compte).

Contrairement aux autres sources du top 5, ce forum bloque l'acces invite a
TOUTE page au-dela de la homepage : `/Forum-X` (index de sous-forum) et
`/Thread-X` (page de fil individuelle) renvoient HTTP 403 meme pour une URL
valide -- verifie, ce n'est pas une question de technique de scraping mais
d'un vrai controle d'acces necessitant un compte. Les flux de syndication
(`/syndication.php`, `/misc.php?action=syndication`) sont bloques de la meme
maniere.

Seule la page d'accueil reste consultable sans compte : elle affiche, pour
chaque sous-forum, un widget "dernier message" avec titre + auteur + horaire
(mais pas le contenu du post lui-meme -- c'est precisement la ou s'arrete
l'acces invite). Ce module se limite volontairement a cette extraction :
explorer plus loin exigerait de creer un compte sur ce forum, une decision
qui n'est pas prise ici (voir discussion projet).

⚠️ RE-VERIFIE LE 2026-08-28, ne pas retenter. Trois variantes d'URL testees
sur quatre fils reels (`?action=lastpost` tel que le site le donne, l'URL du
fil nettoyee de ce parametre, et `?page=1`) : **HTTP 403 dans les 12 cas**,
avec « you do not have permission » et « please login » dans le corps de la
reponse. Ce n'est donc PAS un parametre d'URL mal choisi qu'on pourrait
contourner -- c'est un controle d'acces serveur. Reponse identique a l'octet
pres (14 543 o) quelle que soit la variante.

Le TITRE reste neanmoins exploitable, et il suffit souvent : sur 93 documents
collectes, le classifieur d'annonces (voir detect/announcement_filter.py) en
retient **15 comme annonces de fuite reelles** -- « [AE] 11.6GB
lookinsure.com Database Leaks », « [France] PagesJaunes.fr 3.47M », « [UK]
joaillerie-exemple | 700k Customers ». Les titres nomment le pays, le volume et le
domaine victime. C'est tout ce dont la detection a besoin, sans compte."""

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

KNOWN_BREACHFORUMS_GUEST_HOSTS = (
    "pwnfrm7rbf6kyerigxi677lcz5ifmoagdbqqknwdu2by27wfdst5qmqd.onion",
)


@dataclass(frozen=True)
class ThreadPreview:
    title: str
    thread_url: str
    author: str | None
    last_post_label: (
        str | None
    )  # texte tel qu'affiche (ex: "32 minutes ago"), pas parse en date


def is_breachforums_guest_url(url: str) -> bool:
    return any(host in url for host in KNOWN_BREACHFORUMS_GUEST_HOSTS)


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _is_onion(url: str) -> bool:
    return url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")


@with_retry
def _fetch_homepage(base_url: str) -> str:
    polite_delay()
    session = _build_session()
    response = session.get(
        base_url,
        headers={"User-Agent": pick_user_agent()},
        timeout=70,
        verify=not _is_onion(base_url),
    )
    response.raise_for_status()
    return response.text


def parse_homepage_threads(html_text: str, base_url: str) -> list[ThreadPreview]:
    """Extrait les widgets "dernier message" (`.forums__last-post`) de la page
    d'accueil. Deduplique par URL de fil : le meme thread peut apparaitre
    plusieurs fois (rubriques imbriquees) sans etre un contenu different."""
    soup = BeautifulSoup(html_text, "html.parser")
    seen_urls: set[str] = set()
    previews: list[ThreadPreview] = []

    for cell in soup.select(".forums__last-post"):
        link = cell.select_one('a[href*="Thread-"]')
        if link is None or not link.get("href"):
            continue
        thread_url = urljoin(base_url, link["href"])
        if thread_url in seen_urls:
            continue
        seen_urls.add(thread_url)

        title = link.get("title") or link.get_text(strip=True)
        author_link = cell.select_one('a[href*="User-"]')
        time_span = cell.select_one("span[title]")

        previews.append(
            ThreadPreview(
                title=title,
                thread_url=thread_url,
                author=author_link.get_text(strip=True) if author_link else None,
                last_post_label=time_span.get_text(strip=True) if time_span else None,
            )
        )

    return previews


def fetch_homepage_threads(base_url: str) -> list[ThreadPreview]:
    try:
        html_text = _fetch_homepage(base_url)
    except Exception:
        logger.exception(
            "BreachForums (guest): echec recuperation homepage %s", base_url
        )
        return []
    return parse_homepage_threads(html_text, base_url)
