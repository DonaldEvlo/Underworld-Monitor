"""Noms des fichiers exportés (rapport PDF, paquet STIX). Logique pure."""

from __future__ import annotations

import re
import unicodedata


def nom_de_fichier(sujet: str) -> str:
    """Sujet -> fragment de nom de fichier ASCII.

    Les accents sont TRANSLITTERES avant le filtrage : sans cela « declaree »
    accentue devenait « d-clar-e » dans le nom du PDF, puis dans celui du
    paquet STIX (constate le 2026-10-01). Une seule fonction pour les deux.
    """
    ascii_ = unicodedata.normalize("NFKD", sujet).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-").lower() or "alerte"
