"""Verification de vivacite des liens mentionnes dans les documents collectes
-- mesure de fiabilite d'une annonce ("le dump annonce est-il reellement en
ligne ?") plutot que de la donnee elle-meme.

Perimetre volontairement limite au STATUT et a des metadonnees legeres
(code HTTP, titre de page, Content-Type, Content-Length annonce) : le corps
de la reponse n'est JAMAIS persiste ni retourne. Verifier qu'un lien vers un
hebergeur de fuite repond encore est un signal de gravite pour l'analyste ;
telecharger ce qu'il heberge serait un rapatriement de donnee fuitee, interdit
par CONTRIBUTING.md §2. La lecture du corps s'arrete donc des que le `<title>` est
trouve (voir _read_title), avec un plafond dur (_MAX_TITLE_BYTES).

Observation uniquement (CONTRIBUTING.md §2.1) : une seule requete GET par hote, en
lecture, sans authentification, sans POST, sans tentative de contournement
d'un mur de connexion. Un 401/403 est un resultat ("acces restreint"), jamais
quelque chose a forcer.

OPSEC (CONTRIBUTING.md §2.3) : tout passe par le proxy Tor du projet -- y compris
les URLs clearnet -- avec User-Agent tire aleatoirement et delai de politesse
entre deux requetes, comme onion_healthcheck.py. Ce module ne doit jamais
etre appele depuis un contexte sans acces au reseau `collect`.

Deduplication par hote : un meme hebergeur cite dans 154 documents (constate
sur le corpus reel) n'est interroge qu'une fois par execution -- ce qui borne
le trafic sortant et evite de marteler une source.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.pipeline.collect.politeness import polite_delay
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 45
# Plafond de lecture du corps : on ne lit que le debut de la page, juste assez
# pour esperer y trouver le <title>. Ne jamais augmenter pour "avoir plus de
# contexte" -- ce module n'a pas vocation a rapatrier du contenu.
_MAX_TITLE_BYTES = 8192
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class LinkStatus(str, Enum):
    """Verdict de vivacite d'un lien."""

    ALIVE = "alive"
    # Le serveur repond mais la ressource n'existe plus (404/410) : le cas le
    # plus interessant pour un analyste -- une annonce dont le dump a ete
    # retire est moins credible qu'une annonce dont le lien repond encore.
    GONE = "gone"
    # 401/403 : la ressource existe probablement mais demande une
    # authentification. Resultat en soi, jamais quelque chose a contourner
    # (CONTRIBUTING.md §2.1).
    RESTRICTED = "restricted"
    # Erreur serveur (5xx) : indetermine, ni vivant ni mort.
    SERVER_ERROR = "server_error"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class LinkHealthResult:
    """Resultat pour un hote. Ne contient jamais de corps de reponse -- voir
    docstring du module."""

    url: str
    host: str
    is_onion: bool
    status: LinkStatus
    http_status: int | None
    title: str | None
    content_type: str | None
    content_length: int | None
    checked_at: datetime


def _classify(http_status: int) -> LinkStatus:
    if http_status in (404, 410):
        return LinkStatus.GONE
    if http_status in (401, 403):
        return LinkStatus.RESTRICTED
    if http_status >= 500:
        return LinkStatus.SERVER_ERROR
    return LinkStatus.ALIVE


def _build_session() -> requests.Session:
    """Session proxifiee Tor. `socks5h` : la resolution du nom se fait par Tor
    lui-meme, indispensable pour les .onion (voir tor.build_socks5_proxy_url)
    et souhaitable pour le clearnet (aucune fuite DNS depuis le backend)."""
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=0)))
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _read_title(response: requests.Response) -> str | None:
    """Lit au maximum _MAX_TITLE_BYTES du corps pour en extraire le <title>,
    puis s'arrete. Volontairement partiel : le titre suffit a qualifier une
    page ("File not found", "Login required", nom du dump annonce) sans
    rapatrier son contenu."""
    chunks = bytearray()
    for chunk in response.iter_content(chunk_size=1024):
        chunks.extend(chunk)
        if len(chunks) >= _MAX_TITLE_BYTES:
            break
    match = _TITLE_RE.search(bytes(chunks))
    if not match:
        return None
    title = match.group(1).decode("utf-8", errors="replace")
    return " ".join(title.split())[:200] or None


def check_link(
    url: str, *, session: requests.Session | None = None
) -> LinkHealthResult:
    """Interroge `url` via Tor et retourne son statut + metadonnees legeres.

    Ne leve jamais : une URL injoignable est un resultat normal (site hors
    ligne, lien mort -- c'est precisement ce qu'on mesure), pas une erreur
    applicative. Meme regle que services/collect_service.py."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_onion = host.endswith(".onion")
    now = datetime.now(timezone.utc)

    # ⚠️ ALLOWLIST DE SCHEMA, defense en profondeur. La protection SSRF de fond
    # est le routage Tor (la requete part du conteneur `tor`, jamais du reseau
    # `backend` : `127.0.0.1`, `postgres`, `169.254.169.254` sont hors de sa
    # portee). Mais l'URL vient d'un document COLLECTE, donc controlee par un
    # tiers hostile. `file://`, `gopher://`, `ftp://` sont aujourd'hui surs par
    # ACCIDENT (schema non monte -> exception capturee plus bas), pas par
    # decision. On les ecarte explicitement AVANT toute requete : echouer
    # bruyamment sur ce qui sort du perimetre plutot que compter sur une
    # exception fortuite qu'une evolution de `requests` pourrait lever.
    if parsed.scheme not in ("http", "https"):
        logger.debug("Schema non autorise pour la verification de lien: %s", url)
        return LinkHealthResult(
            url=url,
            host=host,
            is_onion=is_onion,
            status=LinkStatus.UNREACHABLE,
            http_status=None,
            title=None,
            content_type=None,
            content_length=None,
            checked_at=now,
        )

    owns_session = session is None
    session = session or _build_session()

    try:
        # `stream=True` : les en-tetes sont disponibles avant que le corps ne
        # soit telecharge, ce qui permet de decider de ne PAS le lire (gros
        # fichier heberge) plutot que de le rapatrier puis le jeter.
        response = session.get(
            url,
            headers={"User-Agent": pick_user_agent()},
            timeout=_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=True,
            # Un .onion s'authentifie par son adresse (derivee de sa cle
            # publique) : un certificat auto-signe y est la norme, pas un
            # signal MITM. Jamais desactive pour un hote clearnet -- meme
            # regle que onion_healthcheck.py.
            verify=not is_onion,
        )
    except Exception:
        logger.debug("Lien injoignable: %s", url, exc_info=True)
        if owns_session:
            session.close()
        return LinkHealthResult(
            url=url,
            host=host,
            is_onion=is_onion,
            status=LinkStatus.UNREACHABLE,
            http_status=None,
            title=None,
            content_type=None,
            content_length=None,
            checked_at=now,
        )

    try:
        content_type = response.headers.get("Content-Type")
        raw_length = response.headers.get("Content-Length")
        try:
            content_length = int(raw_length) if raw_length is not None else None
        except ValueError:
            content_length = None

        # Le titre n'a de sens que sur du HTML. Sur un binaire (l'archive d'un
        # dump), on ne touche pas au corps du tout : les en-tetes suffisent a
        # dire "le fichier est toujours la et pese tant".
        title = None
        if content_type and "html" in content_type.lower():
            title = _read_title(response)

        return LinkHealthResult(
            url=url,
            host=host,
            is_onion=is_onion,
            status=_classify(response.status_code),
            http_status=response.status_code,
            title=title,
            content_type=content_type,
            content_length=content_length,
            checked_at=now,
        )
    finally:
        # Libere la connexion sans consommer le reste du corps.
        response.close()
        if owns_session:
            session.close()


def check_links(urls: list[str]) -> list[LinkHealthResult]:
    """Verifie une liste d'URLs, dedupliquees par hote (voir docstring du
    module) et espacees par un delai de politesse. Sequentiel a dessein : la
    discretion prime sur la vitesse, et le volume reel est faible (152 hotes
    uniques sur le corpus complet)."""
    seen_hosts: set[str] = set()
    to_check: list[str] = []
    for url in urls:
        host = (urlparse(url).hostname or "").lower()
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        to_check.append(url)

    results: list[LinkHealthResult] = []
    session = _build_session()
    try:
        for index, url in enumerate(to_check):
            results.append(check_link(url, session=session))
            if index < len(to_check) - 1:
                polite_delay()
    finally:
        session.close()
    return results
