"""Libelle d'une alerte : ce qu'elle concerne, en une ligne. Logique pure.

⚠️ Une alerte REGIONALE s'intitulait « Afrique — victime non declaree »,
sans nommer la victime : quatre alertes portaient ce meme titre dans la
liste, et l'alerte la plus grave du produit (Compagnie Aérienne Exemple, critique, le
2026-09-24) ne se reconnaissait qu'en ouvrant son dossier. Le nom vient du
TITRE du document publie par le groupe -- sur un site de fuite, un document
est une victime et son titre la nomme.
"""

from __future__ import annotations

_LONGUEUR_MAX = 60


def region_alert_victim(victims: list[str]) -> str | None:
    """La victime SEULE (« Compagnie Aérienne Exemple », « X +2 »), ou None.

    ⚠️ Pour la liste des alertes : le suffixe « — victime non declaree
    (Afrique) », repete sur 26 lignes, tronquait le nom de la victime -- la
    seule partie qui distingue une ligne d'une autre. Le contexte passe dans
    un badge a cote.
    """
    noms = [v.strip() for v in victims if v and v.strip()]
    if not noms:
        return None
    premier = noms[0]
    if len(premier) > _LONGUEUR_MAX:
        premier = premier[: _LONGUEUR_MAX - 1] + "…"
    suite = f" +{len(noms) - 1}" if len(noms) > 1 else ""
    return f"{premier}{suite}"


def region_alert_subject(region: str, victims: list[str]) -> str:
    """« Compagnie Aérienne Exemple — victime non declaree (Afrique) », « X +2 — … »."""
    victime = region_alert_victim(victims)
    if victime is None:
        return f"{region} — victime non déclarée"
    return f"{victime} — victime non déclarée ({region})"
