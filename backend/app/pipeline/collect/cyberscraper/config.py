from app.core.config import settings
from app.pipeline.collect.cyberscraper.src.scrapers.tor.tor_config import TorConfig
from app.pipeline.collect.cyberscraper.src.scrapers.playwright_scraper import (
    ScraperConfig,
)
from app.pipeline.collect.useragents import USER_AGENT_POOL, pick_user_agent


def build_tor_config(debug: bool = False) -> TorConfig:
    """Traduit `app.core.config.settings` vers la `TorConfig` attendue par `TorScraper`
    (host/port du conteneur `tor` du docker-compose, pool de User-Agents partagé)."""
    return TorConfig(
        socks_host=settings.TOR_SOCKS_HOST,
        socks_port=settings.TOR_SOCKS_PORT,
        control_host=settings.TOR_CONTROL_HOST,
        control_port=settings.TOR_CONTROL_PORT,
        debug=debug,
        max_retries=3,
        timeout=120,
        auto_renew_circuit=True,
        # `verify_connection` fait un aller-retour complet et séparé vers
        # check.torproject.org avant CHAQUE fetch — utile pour un scrape manuel
        # ponctuel, mais ça double le trafic Tor et les points de défaillance en
        # collecte automatisée répétée (constaté : la moitié des échecs venait de
        # cette vérification, pas du fetch réel).
        verify_connection=False,
        user_agents=list(USER_AGENT_POOL),
    )


def build_scraper_config(
    debug: bool = False, *, extended_wait: bool = False
) -> ScraperConfig:
    """Config du scraper Playwright/Patchright pour les sources clearnet (paste sites)
    et les sources onion marquées `requires_js` (voir adapter.py).

    `extended_wait=True` : pour un site avec écran d'attente anti-bot côté JS (ex:
    file d'attente de Dread) — un vrai navigateur patiente naturellement l'écran,
    il faut juste lui laisser le temps nécessaire au lieu du délai d'une page
    classique (30s/2s). Ne change rien à la protection elle-même, seulement le
    temps qu'on accorde au navigateur pour la traverser normalement.
    """
    return ScraperConfig(
        use_stealth=True,
        simulate_human=False,
        bypass_cloudflare=True,
        headless=True,
        debug=debug,
        max_retries=3,
        timeout=180_000 if extended_wait else 30_000,
        delay_after_load=20 if extended_wait else 2,
    )


__all__ = ["build_tor_config", "build_scraper_config", "pick_user_agent"]
