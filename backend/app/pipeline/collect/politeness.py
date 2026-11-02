import random
import time

from tenacity import retry, stop_after_attempt, wait_exponential

MIN_DELAY_SECONDS = 3
MAX_DELAY_SECONDS = 9


def polite_delay() -> None:
    """Pause aléatoire entre deux requêtes pour ne pas marteler une source."""
    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))


def with_retry(func):
    """Retry exponentiel (3 tentatives) pour les fetchers réseau.

    ⚠️ `reraise=True` n'est PAS un détail. Sans lui, tenacity remplace
    l'exception d'origine par un `RetryError`, dont le message est
    « RetryError[<Future at 0x… state=finished raised ValueError>] » : le
    motif réel de l'échec est perdu, et c'est ce texte-là qui remontait
    jusqu'à l'interface. Mesuré le 2026-09-04 sur XSSF, dont le diagnostic
    exact (page d'anti-bot) était calculé puis effacé par l'enrobage.
    """
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )(func)
