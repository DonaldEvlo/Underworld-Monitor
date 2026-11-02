import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import settings


def setup_logging() -> None:
    """Logs structurés JSON — traçabilité OPSEC (aucune valeur brute ne doit y transiter)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.API_ENV == "development" else logging.INFO)
