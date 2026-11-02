"""Valeur EFFECTIVE d'un fait d'alerte (gravité, pays, secteur).

Ordre de priorité (décisions D3 et D4 du 2026-10-05) :
1. la CORRECTION de l'analyste, avec motif ;
2. la valeur DÉCLARÉE pour l'organisation surveillée (pays, secteur) ;
3. la valeur CALCULÉE par la plateforme ou déclarée par un tiers
   (ransomware.live).

⚠️ Une valeur absente ne remplace jamais une valeur présente : `None` et la
chaîne vide passent leur tour. Logique pure, sans base.
"""

from __future__ import annotations


def effective_value(
    override: str | None, declared: str | None, computed: str | None
) -> str | None:
    for valeur in (override, declared, computed):
        if valeur:
            return valeur
    return None


def origin_of(
    override: str | None, declared: str | None, computed: str | None
) -> str | None:
    """D'où vient la valeur effective : `analyst`, `organization`, `computed`
    ou None. Affiché à côté de la valeur : un pays sans origine ne se
    vérifie pas."""
    if override:
        return "analyst"
    if declared:
        return "organization"
    if computed:
        return "computed"
    return None
