"""Alias d'hôtes : une source déménagée garde son parser dédié (2026-10-05).

Nos parsers sont choisis sur l'HÔTE de l'adresse (`dls/scraper.pick_parser`).
Changer l'URL d'une source en base faisait donc retomber le site sur le
collecteur générique — collecte « réussie », un seul bloc au lieu d'un
document par victime, aucune erreur. Piège rencontré trois fois (DARKNET ARMY,
DRAGON FORCE, puis à chaque miroir).

Ce module ramène un hôte à l'hôte d'ORIGINE de sa source : `canonical_host`
suit la chaîne nouvelle adresse → ancienne adresse. Les alias viennent de la
base (changements d'adresse appliqués) par un CHARGEUR injecté au démarrage
de l'API et du worker : ce module reste sans dépendance à la base.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Relecture au plus une fois par minute : une bascule prend effet vite sans
# interroger la base à chaque choix de parser.
_TTL_SECONDS = 60
# Une chaîne d'alias plus longue trahit une boucle (A -> B -> A) : on s'arrête.
_MAX_SAUTS = 10

_chargeur: Callable[[], dict[str, str]] | None = None
_cache: dict[str, str] = {}
_expire_a = 0.0
_temporaires: dict[str, str] = {}


def configure(chargeur: Callable[[], dict[str, str]] | None) -> None:
    """Installe le chargeur d'alias {nouvel hôte: ancien hôte}."""
    global _chargeur, _expire_a, _cache
    _chargeur = chargeur
    _cache = {}
    _expire_a = 0.0


def invalidate() -> None:
    """À appeler après une bascule : relecture au prochain choix de parser."""
    global _expire_a
    _expire_a = 0.0


def _alias() -> dict[str, str]:
    global _cache, _expire_a
    if _chargeur is not None and time.monotonic() >= _expire_a:
        try:
            _cache = dict(_chargeur())
        except Exception:
            # ⚠️ Base indisponible : on garde les derniers alias connus plutôt
            # que de faire retomber les sources déménagées sur le générique.
            logger.warning(
                "Alias d'hôtes illisibles, derniers connus conservés", exc_info=True
            )
        _expire_a = time.monotonic() + _TTL_SECONDS
    return {**_cache, **_temporaires}


def canonical_host(host: str | None) -> str:
    """Hôte d'origine de la source à laquelle `host` appartient."""
    courant = (host or "").lower()
    alias = _alias()
    for _ in range(_MAX_SAUTS):
        suivant = alias.get(courant)
        if not suivant or suivant == courant:
            break
        courant = suivant
    return courant


@contextmanager
def temporary(mapping: dict[str, str]) -> Iterator[None]:
    """Alias valables le temps d'une VÉRIFICATION : on lit une adresse
    candidate avec le parser de la source, sans rien enregistrer."""
    precedents = dict(_temporaires)
    _temporaires.update({k.lower(): v.lower() for k, v in mapping.items()})
    try:
        yield
    finally:
        _temporaires.clear()
        _temporaires.update(precedents)
