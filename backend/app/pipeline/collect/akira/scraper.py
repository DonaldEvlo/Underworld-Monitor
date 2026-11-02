"""Collecte des annonces de victimes publiees sur le site de fuite du groupe
ransomware Akira.

Le site presente une interface "terminal" simulee (librairie jQuery Terminal)
dont le texte visible ne contient PAS les vraies donnees a l'affichage
initial : la commande "leaks" declenche cote client un appel JSON interne,
`/l?page=N&sort=date:desc`, trouve par interception du trafic reseau pendant
un clic simule (Playwright). Cet appel repond directement a une requete HTTP
simple, sans JavaScript ni navigateur -- verifie, aucune protection dessus.

IMPORTANT (regle OPSEC/ethique du projet, voir AGENTS.md #1 -- observation
uniquement, jamais de redistribution de donnees fuitees) : ce module ne
recupere que le TEXTE des annonces (nom de victime, description, date). Le
champ "lien de telechargement" pointe vers l'archive de donnees volees
elle-meme -- il est conserve comme metadonnee texte (indicateur), mais AUCUNE
requete n'est jamais emise vers cette URL par ce module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from app.pipeline.collect.host_aliases import canonical_host
from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_LEAKS_ENDPOINT = "/l"
# Filet de securite si la pagination est absente/mal formee dans la reponse :
# borne le nombre de pages meme si `_max_page_from_pagination` retournait par
# erreur une valeur aberrante.
_MAX_PAGES_SAFETY_CAP = 200
# Format de marquage "jQuery Terminal" observe : [[style;;;;URL]texte_du_lien]
_LINK_RE = re.compile(r"\[\[[^\]]*;(https?://[^\]]+)\]download\]", re.IGNORECASE)
_PAGE_RE = re.compile(r"page=(\d+)")

# Connu pour servir la meme structure /l : l'adresse enregistree en base et
# celle que la page qualifie elle-meme d'"unique lien correct" (voir
# l'avertissement d'usurpation affiche sur akiral2iz...). On ne tranche pas
# laquelle est authentique -- les deux sont routees vers ce collecteur.
KNOWN_AKIRA_HOSTS = (
    "akiral2iz6a7qgd3ayp3l6yub7xx2uep76idk3u2kollpj5z3z636bad.onion",
    "akiralkzxzq2dsrzsrvbr2xgbbu2wgsmxryd4csgfameg52n7efvr2id.onion",
)


@dataclass(frozen=True)
class AkiraLeak:
    date: str
    name: str
    desc: str
    data_link: str | None  # indicateur textuel seulement, jamais suivi par ce module


def is_akira_url(url: str) -> bool:
    # Hôte d'origine aussi : un déménagement appliqué garde ce collecteur.
    origine = canonical_host(urlparse(url).hostname)
    return any(host in url or host in origine for host in KNOWN_AKIRA_HOSTS)


def _clean_wrapped_text(raw: str) -> str:
    """Le texte renvoye par l'API est pre-wrappe a largeur fixe pour
    l'affichage terminal (retour a la ligne au milieu d'un mot inclus). Les
    lignes vides (`\\n\\n`) sont de vrais sauts de paragraphe a garder ; les
    `\\n` simples sont des artefacts de wrap a supprimer -- l'espace de fin de
    mot est deja present avant le `\\n` quand la coupure tombe entre deux
    mots (confirme par inspection : "beverag\\nes." -> "beverages.", "needs \\n
    of" -> "needs of")."""
    normalized = re.sub(r"\n{2,}", "\x00", raw)
    normalized = normalized.replace("\n", "")
    return normalized.replace("\x00", "\n\n").strip()


def _extract_link(raw_url_field: str) -> str | None:
    match = _LINK_RE.search(raw_url_field)
    return match.group(1) if match else None


def _max_page_from_pagination(pagination: list[str]) -> int:
    pages_found = [
        int(m.group(1)) for entry in pagination for m in _PAGE_RE.finditer(entry)
    ]
    return max(pages_found, default=1)


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


@with_retry
def _fetch_page(base_url: str, page: int) -> dict:
    polite_delay()
    session = _build_session()
    url = f"{base_url.rstrip('/')}{_LEAKS_ENDPOINT}?page={page}&sort=date:desc"
    response = session.get(
        url,
        headers={
            "User-Agent": pick_user_agent(),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
        timeout=70,
        # Certificat auto-signe sur .onion : normal, cf. onion_healthcheck.py
        # (l'authentification vient de l'adresse .onion elle-meme, pas d'une CA).
        verify=False,
    )
    response.raise_for_status()
    return response.json()


def _parse_leaks(payload: dict) -> list[AkiraLeak]:
    return [
        AkiraLeak(
            date=obj.get("date", ""),
            name=_clean_wrapped_text(obj.get("name", "")),
            desc=_clean_wrapped_text(obj.get("desc", "")),
            data_link=_extract_link(obj.get("url", "")),
        )
        for obj in payload.get("objects", [])
    ]


def fetch_akira_leaks(base_url: str, max_pages: int | None = None) -> list[AkiraLeak]:
    """Recupere toutes les annonces de victimes (ou seulement les `max_pages`
    premieres pages si fourni -- utile pour un test rapide sans parcourir la
    soixantaine de pages a chaque appel)."""
    first_payload = _fetch_page(base_url, 1)
    total_pages = _max_page_from_pagination(first_payload.get("pagination", []))
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)
    total_pages = min(total_pages, _MAX_PAGES_SAFETY_CAP)

    leaks = _parse_leaks(first_payload)
    for page_num in range(2, total_pages + 1):
        try:
            payload = _fetch_page(base_url, page_num)
        except Exception:
            logger.exception(
                "Akira: echec recuperation page %d, arret de la pagination", page_num
            )
            break
        leaks.extend(_parse_leaks(payload))

    return leaks
