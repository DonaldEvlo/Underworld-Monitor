"""Import/rafraichissement de la liste de forums depuis la source amont
(fastfire/deepdarkCTI sur GitHub).

Deux etapes bien distinctes :
1. Recuperer `forum.md` depuis GitHub -- HTTPS direct (clearnet), PAS via Tor.
   Ce n'est pas de la "collecte" au sens des sources surveillees (AGENTS.md
   regle 3) : on lit un depot logiciel public, comme on le ferait pour toute
   dependance, pas une adresse dark web a proteger operationnellement.
2. Tester chaque adresse .onion NON DEJA CONNUE via `onion_healthcheck`
   (celui-la, via Tor -- ce sont bien des sources a tester). Les adresses
   deja presentes en base (au sens `normalize_url`, cf. core/url_utils.py) ne
   sont ni retestees ni modifiees : ce module n'ajoute que du neuf, il ne
   touche jamais aux sources existantes."""

from __future__ import annotations

import logging

import requests

from app.pipeline.collect.onion_healthcheck import (
    check_onion_entries,
    parse_onion_entries_from_text,
)

logger = logging.getLogger(__name__)

_REPO_RAW_BASE = "https://raw.githubusercontent.com/fastfire/deepdarkCTI/main"
DEFAULT_FORUM_MD_URL = f"{_REPO_RAW_BASE}/forum.md"
_FETCH_TIMEOUT = 30

# Listes importees depuis deepdarkCTI.
#
# **`forum.md` UNIQUEMENT** -- decision de projet (2026-08-22). Le depot
# contient d'autres listes exploitables (`ransomware_gang.md` a lui seul
# apportait 583 adresses inconnues, `markets.md` 79, `search_engines.md` 55),
# mais le perimetre retenu se limite aux forums.
#
# La structure en tuple est conservee : elle permet d'elargir plus tard sans
# retoucher `fetch_all_lists`, et documente que le choix est un choix, pas une
# limite technique. Ne PAS ajouter de liste sans validation explicite.
IMPORTED_LIST_URLS: tuple[str, ...] = (DEFAULT_FORUM_MD_URL,)


def fetch_all_lists(urls: tuple[str, ...] = IMPORTED_LIST_URLS) -> str:
    """Concatene les listes markdown importees.

    Retourne un seul texte : `parse_onion_entries_from_text` deduplique deja
    par URL, donc une adresse presente dans deux listes n'est comptee qu'une
    fois. Une liste indisponible est journalisee et ignoree -- perdre une
    liste ne doit pas faire echouer l'import des autres."""
    parts = []
    for url in urls:
        try:
            parts.append(fetch_forum_md(url))
        except Exception:
            logger.exception("Import GitHub: liste indisponible, ignoree: %s", url)
    return "\n".join(parts)


def fetch_forum_md(url: str = DEFAULT_FORUM_MD_URL) -> str:
    response = requests.get(
        url, timeout=_FETCH_TIMEOUT, headers={"User-Agent": "threat-intel-platform"}
    )
    response.raise_for_status()
    return response.text


def find_new_candidates(
    markdown_text: str, existing_normalized_urls: set[str], normalize: callable
) -> list[tuple[str, str]]:
    """Parse le markdown et ne garde que les entrees .onion dont l'URL normalisee
    n'est pas deja une source connue -- ne re-teste ni ne recree jamais une
    source existante."""
    all_entries = parse_onion_entries_from_text(markdown_text)
    return [
        (name, url)
        for name, url in all_entries
        if normalize(url) not in existing_normalized_urls
    ]


__all__ = [
    "DEFAULT_FORUM_MD_URL",
    "IMPORTED_LIST_URLS",
    "fetch_forum_md",
    "fetch_all_lists",
    "find_new_candidates",
    "check_onion_entries",
]
