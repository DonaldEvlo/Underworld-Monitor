"""Nom d'affichage d'un groupe attaquant, a partir du nom de sa source.

Logique pure. Vivait dans le routeur `api/routers/stats.py` sous le nom
`_nom_de_groupe`, et etait importee de la par `credibility_service` -- un
service qui dependait d'un routeur (couches inversees). Deplacee le
2026-09-25.
"""

from __future__ import annotations

import re

# Suffixes techniques accoles au nom de source : ils decrivent notre collecte,
# pas le groupe. « LOCKBIT 3.0 (New Dark mirror 1) (DLS) » -> « LOCKBIT 3.0 ».
# ⚠️ « (BASHEE) » est CONSERVE : c'est l'autre nom du gang, pas un detail de
# plomberie (verrouille par test).
_SUFFIXES_SOURCE = re.compile(
    r"\s*\((?:DLS|dark|new dark mirror[^)]*|ransomware leak site|mirror[^)]*)\)\s*$",
    re.IGNORECASE,
)


def group_display_name(source_name: str) -> str:
    """Retire les suffixes techniques, en boucle (ils se cumulent)."""
    precedent = None
    nom = source_name.strip()
    while nom != precedent:
        precedent = nom
        nom = _SUFFIXES_SOURCE.sub("", nom).strip()
    return nom or source_name
