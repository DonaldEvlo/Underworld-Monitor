"""Qualification de la nature d'une annonce a partir de son titre (fuite de
base, logs de stealer, combolist, acces vendu...). Logique pure (voir
CONTRIBUTING.md).

Quatrieme detecteur de la famille "exploiter ce que la source declare" apres
victim.py, distribution.py et topic.py. Ici la donnee exploitee est le **titre
de la publication**, pose par les collecteurs en tete de `content` sous la forme
"Titre: ..." (voir collect/mybb_latest/adapter.py, collect/exilio404/adapter.py,
collect/breachforums_guest/adapter.py).

Ce que ca apporte, que rien d'autre ne capture : les autres detecteurs
repondent a "quelle valeur a fuite ?" (un email, un domaine) ou "qui est
touche ?" (victim.py). Celui-ci repond a "**de quoi s'agit-il ?**" -- une
annonce de base de donnees compromise n'a pas la meme portee qu'une revente de
combolist recyclee. Constate en base : 44 des 97 titres MyBB annoncent
explicitement une fuite ("pintando.com.mx database 2025-2026 breached",
"Telekom Serbia - DB 650k+ Lines"), information aujourd'hui perdue.

`validated=True` : la categorie est deduite de mots-cles explicites ecrits par
l'annonceur lui-meme, pas d'une inference sur le sens du texte. Pas une PII :
c'est une categorie d'evenement.

Perimetre volontairement etroit : uniquement des mots-cles sans ambiguite, sur
la ligne de titre seule. Un titre qui n'en contient aucun ne produit rien --
mieux vaut ne rien dire que de qualifier a tort."""

from __future__ import annotations

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

# Marqueur pose par les adaptateurs de collecte en tete de `content`.
_TITLE_LINE_RE = re.compile(r"^Titre:\s*(?P<title>.+?)\s*$", re.MULTILINE)

# Categories d'annonce, associees aux mots-cles qui les designent sans
# ambiguite dans un titre. Ordre significatif : la premiere categorie qui
# matche gagne, du plus specifique au plus general (un titre "ULP LOGS" est
# des logs de stealer, pas une simple combolist).
#
# `\b` sur chaque terme : "db" ne doit pas matcher dans "dbeaver", "logs" ne
# doit pas matcher dans "blogs" (voir tests).
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    # Logs d'infostealer (ULP = url:login:password), le format le plus courant
    # de revente d'acces sur ces forums.
    ("stealer_logs", ("stealer", "ulp", "redline", "raccoon", "lumma", "vidar")),
    # Base de donnees compromise et publiee.
    ("database_leak", ("database", "db", "dump", "sql")),
    # Listes d'identifiants recyclees/agregees.
    ("combolist", ("combo", "combolist", "cracked")),
    # Acces a un systeme vendu (RDP, VPN, panel...).
    ("access_sale", ("rdp", "vpn access", "shell access", "webshell", "cpanel")),
    # Annonce de compromission sans precision de format.
    ("breach", ("breached", "breach", "hacked", "leaked", "leak", "pwned")),
]


def _categorize(title: str) -> str | None:
    """Categorie de l'annonce, ou None si le titre ne contient aucun marqueur
    explicite -- ne jamais qualifier au jugé."""
    lowered = title.casefold()
    for category, keywords in _CATEGORIES:
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return category
    return None


def find_announcements(text: str) -> list[RawMatch]:
    """Retourne la nature de l'annonce declaree par le titre de `text`.

    Au plus une detection par categorie : un titre unique decrit un seul
    evenement, la dedup evite qu'un document agregeant plusieurs annonces ne
    repete la meme categorie."""
    matches = []
    seen: set[str] = set()

    for title_match in _TITLE_LINE_RE.finditer(text):
        category = _categorize(title_match.group("title"))
        if category is None or category in seen:
            continue
        seen.add(category)
        matches.append(
            RawMatch(
                type=DetectionType.ANNOUNCEMENT,
                value_masked=category,
                value_hash=hash_value(category),
                validated=True,
            )
        )

    return matches
