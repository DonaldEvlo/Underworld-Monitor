"""Choix du collecteur d'une source, selon son URL.

Vivait dans le routeur `api/routers/sources.py` (`_pick_collector`), d'ou le
worker Celery l'importait : une tache de fond dependait d'un routeur HTTP
(couches inversees). Deplace a l'identique le 2026-09-25.
"""

from __future__ import annotations

from typing import Any

from app.pipeline.collect.akira.adapter import AkiraCollector
from app.pipeline.collect.akira.scraper import is_akira_url
from app.pipeline.collect.base import Collector
from app.pipeline.collect.breachforums_guest.adapter import BreachForumsGuestCollector
from app.pipeline.collect.breachforums_guest.scraper import is_breachforums_guest_url
from app.pipeline.collect.cyberscraper.adapter import CyberScraperCollector
from app.pipeline.collect.dls.adapter import DlsCollector
from app.pipeline.collect.dls.fetch import fetch_dls_html
from app.pipeline.collect.dls.scraper import is_supported_dls_url
from app.pipeline.collect.doxbyte.adapter import DoxByteCollector, is_known_doxbyte_url
from app.pipeline.collect.dread.adapter import (
    INTERACTIVE_MAX_BODIES,
    DreadCollector,
    is_dread_url,
)
from app.pipeline.collect.exilio404.adapter import (
    Exilio404Collector,
    is_known_exilio404_url,
)
from app.pipeline.collect.mybb_latest.adapter import (
    MyBBLatestCollector,
    is_known_mybb_url,
)
from app.pipeline.collect.ransomlook.adapter import RansomLookCollector
from app.pipeline.collect.ransomlook.scraper import is_ransomlook_url
from app.pipeline.collect.telegram.adapter import (
    TelegramChannelCollector,
    is_telegram_url,
)
from app.pipeline.collect.telegram.mtproto_adapter import MtprotoChannelCollector
from app.pipeline.collect.telegram.mtproto_client import (
    is_configured as telegram_api_configured,
)
from app.pipeline.collect.xenforo_latest.adapter import (
    XenForoLatestPostsCollector,
    is_known_xenforo_url,
)
from app.pipeline.collect.xssf.adapter import XssfCollector
from app.pipeline.collect.xssf.scraper import is_xssf_url
from app.pipeline.detect.announcement_filter import source_publishes_victims


# `source` : tout objet portant `.url` (modele SQLAlchemy `Source`, contrat
# Pydantic, doublure de test). Type `Any` et non un Protocol : mypy ne
# reconnait pas un attribut `Mapped[str]` comme satisfaisant `url: str`
# (limite connue), et importer le modele ici ferait dependre `pipeline/`
# de la couche base.
def pick_collector(source: Any) -> Collector:
    """Certaines sources exigent un collecteur dedie plutot que le
    `CyberScraperCollector` generique -- leur contenu reel n'est pas dans le
    HTML servi tel quel (Akira, XSSF) ou beneficie d'un flux dedie couvrant
    tout le site plutot qu'une seule page (XenForo). Voir le module de chaque
    collecteur pour le detail de la decouverte."""
    if is_ransomlook_url(source.url):
        return RansomLookCollector()
    if is_akira_url(source.url):
        return AkiraCollector()
    if is_xssf_url(source.url):
        return XssfCollector()
    if is_known_xenforo_url(source.url):
        return XenForoLatestPostsCollector()
    if is_breachforums_guest_url(source.url):
        return BreachForumsGuestCollector()
    if is_known_mybb_url(source.url):
        return MyBBLatestCollector()
    if is_known_exilio404_url(source.url):
        return Exilio404Collector()
    if is_known_doxbyte_url(source.url):
        return DoxByteCollector()
    if is_supported_dls_url(source.url):
        # DLS a structure connue (LockBit, NIGHT SPIRE) : un document par
        # victime, avec date et volume. Le generique n'en produisait qu'un
        # seul pour tout le site -- voir dls/scraper.py.
        return DlsCollector(html_fetcher=fetch_dls_html)
    if is_dread_url(source.url):
        # Budget de corps reduit : ce selecteur ne sert QUE les chemins
        # interactifs (POST /{id}/collect et le batch « Collecter tout »).
        # A pleine charge Dread demande ~24 min et monopolise l'un des 5
        # workers du batch pendant que les autres sources rendent en ~1 min.
        # Le cycle complet reste celui planifie chaque jour, qui instancie
        # `DreadCollector()` sans argument (voir worker/tasks/dread_tasks.py).
        # `collect.all_active_sources` n'est pas concerne : il exclut Dread.
        return DreadCollector(max_bodies=INTERACTIVE_MAX_BODIES)
    if is_telegram_url(source.url):
        # Canal Telegram public. Client API (MTProto) si un compte de lecture
        # est configure et connecte -- 100 messages, metadonnees des fichiers,
        # canaux sans apercu web --, sinon l'apercu web t.me/s/ sans compte.
        # Dans les deux cas traite comme un forum, pas un site de fuite.
        if telegram_api_configured():
            return MtprotoChannelCollector()
        return TelegramChannelCollector()
    return CyberScraperCollector()


def publishes_victims(source: Any) -> bool:
    """La source est-elle un site qui PUBLIE ses victimes (site de fuite,
    AKIRA, RansomLook) ? Decide sur le collecteur reellement choisi, jamais
    sur le nom : un site de fuite sans parser dedie retombe sur le collecteur
    generique et n'est alors pas traite comme tel (meme autorite que
    `announcement_filter.source_publishes_victims`)."""
    return source_publishes_victims(pick_collector(source).COLLECTOR_NAME)
