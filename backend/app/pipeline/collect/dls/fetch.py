"""Recuperation HTML d'un DLS, via Tor.

Isole du parsing (scraper.py) et de la construction de documents
(adapter.py) : le collecteur recoit ce fetcher par injection, ce qui laisse
les deux autres modules testables sans reseau.

Utilise `requests` plutot que Playwright : mesure du 2026-08-24, LockBit et
NIGHT SPIRE servent leur liste de victimes directement en HTML (819 Ko et
818 Ko de reponse, structure complete presente). Un navigateur couterait
~15 s par page pour un resultat identique. Un DLS a rendu JS demanderait un
fetcher different -- l'injection rend ce changement local."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
import urllib3

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

# Certificat auto-signe : la norme sur .onion, ou l'adresse elle-meme est la
# racine de confiance (meme raisonnement que onion_healthcheck.py).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def verify_tls_for(url: str) -> bool:
    """Verifier le certificat, SAUF pour un `.onion`.

    Un `.onion` s'authentifie par son adresse (derivee de sa cle) et Tor
    chiffre la liaison de bout en bout : son certificat, presque toujours
    auto-signe, n'apporte rien et ferait echouer la requete. Un site CLEARNET,
    lui, n'est authentifie QUE par son certificat -- sans verification, le
    noeud de sortie Tor pourrait se faire passer pour lui.

    ⚠️ Jusqu'au 2026-09-25, `verify=False` etait pose sans condition : sans
    effet tant que ce collecteur ne recoit que des `.onion`, mais un DLS
    clearnet ajoute un jour aurait ete collecte sans verification, en
    silence. Dans le doute (URL illisible), on VERIFIE.

    `hostname` plutot qu'un decoupage de chaine : il retire le port et la
    casse (`X.ONION:8080` reste un `.onion`)."""
    hote = (urlparse(url).hostname or "").rstrip(".")
    return not hote.endswith(".onion")


_TIMEOUT_SECONDS = 90


class _TransientFetchError(RuntimeError):
    """Echec susceptible de reussir au reessai -- `with_retry` (tenacity) ne
    se declenche que sur exception, jamais sur une valeur de retour."""


@with_retry
def fetch_dls_html(url: str) -> str:
    """Recupere le HTML d'un DLS via Tor.

    `resolve_via_proxy=True` (socks5h) est OBLIGATOIRE : sans lui le nom
    .onion serait resolu localement, ou il n'existe pas -- toutes les requetes
    echoueraient en ConnectionError (constate le 2026-08-24)."""
    polite_delay()
    proxy = build_socks5_proxy_url(resolve_via_proxy=True)
    try:
        response = requests.get(
            url,
            proxies={"http": proxy, "https": proxy},
            headers={"User-Agent": pick_user_agent()},
            timeout=_TIMEOUT_SECONDS,
            verify=verify_tls_for(url),
        )
    except Exception as exc:
        raise _TransientFetchError(f"{type(exc).__name__} sur {url}") from exc

    if response.status_code >= 500:
        raise _TransientFetchError(f"HTTP {response.status_code} sur {url}")
    return response.text
