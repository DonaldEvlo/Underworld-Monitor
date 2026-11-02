import asyncio
import logging

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.cyberscraper.config import (
    build_scraper_config,
    build_tor_config,
)
from app.pipeline.collect.cyberscraper.extractor import RobustExtractor
from app.pipeline.collect.cyberscraper.src.scrapers.playwright_scraper import (
    PlaywrightScraper,
)
from app.pipeline.collect.cyberscraper.src.scrapers.tor.tor_scraper import TorScraper
from app.pipeline.collect.cyberscraper.src.scrapers.tor.utils import is_onion_url
from app.pipeline.collect.link_extraction import extract_mentioned_urls
from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url, renew_circuit

logger = logging.getLogger(__name__)


class _TransientFetchError(RuntimeError):
    """Echec de recuperation rejouable.

    ⚠️ Existe pour que `@with_retry` ait quelque chose a intercepter. Un
    fetcher qui *retourne* son echec rend le decorateur inerte, sans que rien
    ne le signale : les tentatives annoncees n'ont simplement jamais lieu.
    """


class CyberScraperCollector(Collector):
    """Wrapper autour de CyberScraper (adapté, automatisé) : fetch via `TorScraper`
    pour les .onion classiques, ou `PlaywrightScraper` (proxifié Tor) pour le
    clearnet et les sources .onion marquées `requires_js` (écran d'attente/défi
    JS, ex: Dread), extraction via `RobustExtractor`. Aucune intervention humaine
    (CAPTCHA, chat) — un échec de fetch renvoie une liste vide plutôt que de
    bloquer le cycle.
    """

    def __init__(self) -> None:
        self._extractor = RobustExtractor()

    COLLECTOR_NAME = "cyberscraper"
    COLLECTOR_VERSION = "1"

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        _renew_circuit_safely()
        try:
            html = self._fetch(str(source.url), source.requires_js)
        except Exception:
            logger.exception("Fetch failed for %s after retries", source.url)
            return []

        if not html:
            return []

        extracted = self._extractor.extract(html)
        if not extracted["text"]:
            logger.warning("Empty extraction for %s, skipping", source.url)
            return []

        mentioned_urls = extract_mentioned_urls(
            extracted["text"], exclude_url=str(source.url)
        )
        return [
            self._build_document(
                source,
                str(source.url),
                extracted["text"],
                title=extracted["title"] or None,
                raw_html=html,
                source_meta=(
                    {"mentioned_urls": mentioned_urls} if mentioned_urls else None
                ),
            )
        ]

    @with_retry
    def _fetch(self, url: str, requires_js: bool = False) -> str:
        """Recupere le HTML, ou LEVE.

        ⚠️ Rendre `None` en cas d'echec rendait `@with_retry` purement
        DECORATIF : tenacity ne rejoue que sur exception. Le decorateur etait
        donc en place, visible, et n'avait jamais rejoue une seule tentative --
        exactement le defaut corrige sur `dread/search.py` le 2026-08-19, et
        signale comme non traite ici depuis (CONTRIBUTING.md §8).
        """
        # TorScraper/PlaywrightScraper sont créés ici, à chaque tentative, plutôt
        # qu'une seule fois dans __init__ : chaque appel fait son propre
        # `asyncio.run()`, qui crée ET FERME sa propre event loop. Un scraper
        # (et sa session aiohttp) mis en cache d'un appel à l'autre se retrouve
        # lié à une loop déjà fermée dès le 2e appel — retry ou source suivante
        # d'un batch — d'où des échecs "Event loop is closed" en série.
        polite_delay()
        # Une source .onion avec un écran d'attente/défi JS (ex: file d'attente de
        # Dread) ne peut pas être franchie par TorScraper (simple client HTTP, pas
        # de JS) : elle passe par PlaywrightScraper comme le clearnet, avec un
        # délai étendu pour laisser l'écran se résoudre naturellement.
        if is_onion_url(url) and not requires_js:
            tor_scraper = TorScraper(build_tor_config())
            contenu = asyncio.run(tor_scraper.fetch_content(url))
            # ⚠️ `fetch_content` signale ses echecs par une CHAINE (« Error: … »)
            # ou par None, jamais par une exception : sans cette conversion, le
            # retry ne se declenche pas et une chaine d'erreur serait persistee
            # comme un document.
            if not (contenu or "").strip():
                raise _TransientFetchError(f"Reponse vide pour {url}")
            if contenu.startswith("Error:"):
                raise _TransientFetchError(f"Aucun contenu exploitable pour {url}")
            return contenu

        playwright_scraper = PlaywrightScraper(
            build_scraper_config(extended_wait=requires_js)
        )
        contents = asyncio.run(
            playwright_scraper.fetch_content(url, proxy=build_socks5_proxy_url())
        )
        # ⚠️ Une page VIDE est un echec rejouable, pas un succes. Attrape par
        # test : `contents == [""]` passait le controle (la liste est non vide,
        # la chaine ne commence pas par « Error: ») et etait rendue comme du
        # contenu -- donc jamais rejouee, alors qu'une reponse vide est le
        # symptome typique d'un rendu incomplet sur Tor.
        if not contents or not (contents[0] or "").strip():
            raise _TransientFetchError(f"Reponse vide pour {url}")
        if contents[0].startswith("Error:"):
            raise _TransientFetchError(f"Aucun contenu exploitable pour {url}")
        return contents[0]


def _renew_circuit_safely() -> None:
    """Renouvelle le circuit Tor (nouvelle IP de sortie) une fois par cycle de
    collecte ; ne casse jamais la collecte si le port de contrôle est injoignable
    (ex: dev sans conteneur `tor` démarré)."""
    try:
        renew_circuit()
    except Exception:
        logger.warning(
            "Could not renew Tor circuit, continuing with current circuit",
            exc_info=True,
        )
