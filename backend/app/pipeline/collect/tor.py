import logging
import socket

from stem import Signal
from stem.control import Controller

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_socks5_proxy_url(*, resolve_via_proxy: bool = False) -> str:
    """URL du proxy SOCKS5 vers le conteneur `tor` (règle OPSEC : tout le trafic de
    collecte, y compris le clearnet, passe par ce proxy — jamais l'IP du backend).

    `resolve_via_proxy=True` (schéma `socks5h://`) fait résoudre le nom d'hôte par
    Tor lui-même plutôt que par le backend — nécessaire pour les clients qui ne
    savent pas nativement router les `.onion` (ex: `requests`)."""
    scheme = "socks5h" if resolve_via_proxy else "socks5"
    return f"{scheme}://{settings.TOR_SOCKS_HOST}:{settings.TOR_SOCKS_PORT}"


def renew_circuit() -> None:
    """Force le renouvellement du circuit Tor (NEWNYM) -> nouvelle IP de sortie.

    À appeler entre deux cycles de collecte, en même temps qu'un nouveau
    User-Agent est tiré (voir `useragents.pick_user_agent`), pour ne jamais
    répéter la même paire (IP, UA) sur une source d'un cycle à l'autre.
    """
    # stem.Controller.from_port() exige une IP littérale, pas un nom DNS docker-compose.
    control_ip = socket.gethostbyname(settings.TOR_CONTROL_HOST)

    with Controller.from_port(
        address=control_ip, port=settings.TOR_CONTROL_PORT
    ) as controller:
        controller.authenticate(password=settings.TOR_CONTROL_PASSWORD)
        controller.signal(Signal.NEWNYM)
        logger.info("Tor circuit renewed (NEWNYM)")
