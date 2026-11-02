import asyncio
import logging
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from app.pipeline.collect.cyberscraper.config import build_scraper_config
from app.pipeline.collect.cyberscraper.src.scrapers.playwright_scraper import (
    PlaywrightScraper,
)
from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url

logger = logging.getLogger(__name__)

# Marqueurs de l'écran anti-bot (captcha) observé occasionnellement sur /search/
# (voir découverte du 2026-07-10) — n'apparaît pas sur le reste du site, pas lié à
# un compte connecté (confirmé sur 4 tentatives consécutives avec circuits Tor
# différents : recherche anonyme fonctionne normalement dans l'immense majorité
# des cas). On ne tente jamais de le résoudre automatiquement : on le signale et
# on passe au mot-clé suivant plutôt que de bloquer ou stocker du contenu inutile.
_DDOS_PROTECTION_MARKERS = ("DDOS Protection", "ddos_form")


def build_search_url(base_url: str, keyword: str) -> str:
    """Construit l'URL de recherche interne de Dread (`/search/?q=...`) à partir de
    l'URL de base de la source telle qu'enregistrée en base."""
    return urljoin(base_url, f"/search/?q={quote(keyword)}")


def is_ddos_protection_page(html: str) -> bool:
    return any(marker in html for marker in _DDOS_PROTECTION_MARKERS)


def _parse_item(item, base_url: str) -> dict | None:
    title_link = item.select_one(
        ".post-title a[href^='/post/'], .postTop a.title[href^='/post/']"
    )
    if title_link is None:
        return None

    subdread_link = item.select_one("a[href^='/d/']")
    author_link = item.select_one("a[href^='/u/']")
    date_span = item.select_one("span[title]")
    snippet_el = item.select_one(".comment-body, .postContent")

    return {
        "title": title_link.get_text(strip=True),
        "link": urljoin(base_url, title_link["href"]),
        "subdread": subdread_link.get_text(strip=True) if subdread_link else None,
        "author": author_link.get_text(strip=True) if author_link else None,
        "date": date_span["title"] if date_span else None,
        "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else None,
    }


def parse_search_results(html: str, base_url: str) -> list[dict]:
    """Extrait les fils/commentaires trouvés par la recherche interne de Dread
    (structure réelle observée : `.postBoard > .item[.comment]`, un `.item` par
    résultat — fil trouvé directement ou commentaire correspondant)."""
    soup = BeautifulSoup(html, "html.parser")
    board = soup.select_one(".postBoard")
    if board is None:
        return []

    results = []
    for item in board.select(".item"):
        parsed = _parse_item(item, base_url)
        if parsed is not None:
            results.append(parsed)
    return results


class _TransientFetchError(RuntimeError):
    """Échec de fetch susceptible de réussir au réessai.

    Nécessaire pour que `@with_retry` (tenacity) s'applique : il ne se déclenche
    que sur exception. Retourner `None` en cas d'échec — ce que faisait ce
    module — rendait le décorateur purement décoratif, aucune tentative n'était
    jamais rejouée."""


@with_retry
def _fetch_search_html(url: str) -> str | None:
    # PlaywrightScraper instancié à chaque tentative (pas en cache) : chaque appel
    # fait son propre asyncio.run(), qui crée ET ferme sa propre event loop — un
    # scraper mis en cache d'un appel à l'autre finirait lié à une loop fermée dès
    # la 2e tentative (même bug déjà rencontré sur l'adapter CyberScraper).
    polite_delay()
    scraper = PlaywrightScraper(build_scraper_config(extended_wait=True))
    contents = asyncio.run(scraper.fetch_content(url, proxy=build_socks5_proxy_url()))

    if not contents:
        raise _TransientFetchError(f"Empty scraper response for {url}")

    content = contents[0]
    if content.startswith("Error:"):
        # Mesuré le 2026-08-19 : en recherche parallèle (5 workers), Playwright
        # renvoie régulièrement « Page.content: Unable to retrieve content
        # because the page is navigating » — la page Dread se recharge pendant
        # la lecture. C'est transitoire : le même mot-clé qui échoue dans un lot
        # remonte 20 résultats en séquentiel. On lève pour déclencher le retry
        # au lieu de renvoyer une liste vide silencieuse.
        raise _TransientFetchError(content.splitlines()[0])

    return content


def search_dread_for_keyword(base_url: str, keyword: str) -> list[dict]:
    """Recherche un mot-clé sur la recherche interne de Dread et retourne les
    fils/commentaires trouvés. Renvoie une liste vide si la page anti-bot
    apparaît ou si le fetch échoue après retries — jamais d'exception qui
    bloquerait le cycle sur les mots-clés suivants.

    Ne renouvelle PAS le circuit Tor ici (contrairement aux versions
    precedentes) : avec desormais 100+ mots-cles actifs dans la watchlist, les
    recherches sont executees EN PARALLELE (voir dread.py) -- un renouvellement
    par mot-cle casserait les connexions en cours des autres recherches du
    meme lot. Le circuit est renouvele une seule fois avant de lancer tout le
    lot, voir `_run_dread_search_job`."""
    url = build_search_url(base_url, keyword)
    try:
        html = _fetch_search_html(url)
    except Exception:
        logger.exception("Dread search failed for keyword %r after retries", keyword)
        return []

    if not html:
        return []

    if is_ddos_protection_page(html):
        logger.warning(
            "Dread anti-bot page hit for keyword %r, skipping this cycle", keyword
        )
        return []

    return parse_search_results(html, base_url)
