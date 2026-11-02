"""Qui frappe où : classement des groupes par région (2026-10-05). Logique pure.

Répond à « quels groupes attaquent le plus l'Afrique ? » à partir des
historiques de victimes déjà lus chez ransomware.live (pays DÉCLARÉ par ce
tiers, jamais déduit d'un DNS ou d'une géolocalisation d'IP — règle 1).

⚠️ Aucune victime n'est nommée : seuls des comptes par groupe et par pays
sortent d'ici (`VictimFact` ne porte pas de nom). La vue est donc ouverte au
RSSI au même titre que la menace mondiale de la page Gouvernance.

⚠️ Ce n'est PAS « tous les groupes du monde » : seuls les groupes dont
l'historique est en cache sont comptés (ceux que nous corroborons et ceux
repérés par la localisation des victimes). La couverture est rendue avec le
classement et doit être affichée à côté.

Le drapeau `collected` dit si NOUS lisons le site de ce groupe : la part des
victimes d'une région portée par des groupes non collectés mesure le trou de
couverture, qui est le vrai facteur limitant du produit (CONTRIBUTING.md §6).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.pipeline.alerting.rules import CRITICAL_SECTORS
from app.pipeline.reporting.governance import VictimFact, _aware, _debut_fenetre

MONDE = "Monde"
NON_RENSEIGNE = "non renseigné"
_TOP_PAYS = 5


def normalise_gang(nom: str | None) -> str:
    """« Dragon Force » == « dragonforce » (même règle que la corroboration)."""
    return re.sub(r"[^a-z0-9]", "", (nom or "").lower())


def actors_by_region(
    victimes: list[VictimFact],
    *,
    continent_de: Callable[[str], str | None],
    now: datetime,
    months: int = 12,
    continent: str | None = None,
    country: str | None = None,
    collected: set[str] | frozenset[str] = frozenset(),
    top: int = 15,
) -> dict:
    """Classement des groupes sur la région choisie.

    `continent=None` (ou « Monde ») = le monde entier ; `country` (ISO2) restreint
    à un pays et prime sur le continent. `collected` = identifiants normalisés
    des groupes dont nous lisons le site."""
    now = _aware(now)
    debut = _debut_fenetre(now, months)
    fenetre = [v for v in victimes if debut <= _aware(v.discovered) <= now]

    def continent_of(v: VictimFact) -> str:
        return continent_de((v.country or "").upper()) or NON_RENSEIGNE

    # Totaux par continent : le sélecteur de région affiche ses volumes.
    par_continent = Counter(continent_of(v) for v in fenetre)

    pays = (country or "").strip().upper() or None
    region = None if continent in (None, "", MONDE) else continent
    if pays:
        retenues = [v for v in fenetre if (v.country or "").upper() == pays]
    elif region:
        retenues = [v for v in fenetre if continent_of(v) == region]
    else:
        retenues = fenetre

    total = len(retenues)
    par_gang: dict[str, list[VictimFact]] = {}
    for v in retenues:
        par_gang.setdefault(v.gang, []).append(v)

    collectes = {normalise_gang(g) for g in collected}
    lignes: list[dict[str, Any]] = []
    for gang, vs in par_gang.items():
        pays_gang = Counter((v.country or "").upper() for v in vs if v.country)
        critiques = sum(1 for v in vs if (v.sector or "") in CRITICAL_SECTORS)
        lignes.append(
            {
                "gang": gang,
                "victims": len(vs),
                "share": round(len(vs) / total, 3) if total else None,
                "countries": [
                    {"code": code, "count": n}
                    for code, n in sorted(
                        pays_gang.items(), key=lambda kv: (-kv[1], kv[0])
                    )[:_TOP_PAYS]
                ],
                "country_count": len(pays_gang),
                "critical_sector_share": round(critiques / len(vs), 3),
                "last_discovered": max(_aware(v.discovered) for v in vs).isoformat(),
                "collected": normalise_gang(gang) in collectes,
            }
        )
    # Volume d'abord, nom ensuite : un ordre stable d'un appel à l'autre.
    lignes.sort(key=lambda r: (-r["victims"], r["gang"]))

    victimes_collectees = sum(r["victims"] for r in lignes if r["collected"])
    pays_region = Counter((v.country or "").upper() for v in retenues if v.country)
    return {
        "window_start": debut.date().isoformat(),
        "months": months,
        "continent": region,
        "country": pays,
        "total": total,
        "gangs": len(lignes),
        "unknown_country": sum(1 for v in retenues if not v.country),
        "collected_victims": victimes_collectees,
        "collected_share": round(victimes_collectees / total, 3) if total else None,
        "critical_sector_share": (
            round(
                sum(1 for v in retenues if (v.sector or "") in CRITICAL_SECTORS)
                / total,
                3,
            )
            if total
            else None
        ),
        "actors": lignes[:top],
        "other_actors": max(0, len(lignes) - top),
        "countries": [
            {"code": code, "count": n}
            for code, n in sorted(pays_region.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "continents": [
            {"label": label, "count": n}
            for label, n in sorted(
                par_continent.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    }
