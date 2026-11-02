import random

# Chaînes UA réalistes et cohérentes avec les en-têtes Accept-Language envoyés à côté
# (voir `tor_manager.get_headers` / `politeness.py`). Pool volontairement restreint à
# des navigateurs desktop récents pour rester crédible.
USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


def pick_user_agent() -> str:
    """Tire un User-Agent frais dans le pool — à appeler à chaque nouveau cycle de
    collecte, en cohérence avec le renouvellement de circuit Tor (voir `tor.py`)."""
    return random.choice(USER_AGENT_POOL)
