"""Detection de mentions de volume/ampleur d'un leak annonce publiquement
(nombre d'enregistrements, taille de donnees, nombre de comptes). Logique
pure (voir CONTRIBUTING.md).

Ce n'est PAS une PII : ce sont des chiffres deja publies en clair par
l'annonceur du leak (titre de thread, description de listing) pour vendre/
publiciser sa fuite -- lire et cataloguer ce signal reste de l'observation,
pas de l'extraction de donnees personnelles (voir conversation projet : ce
detecteur existe justement pour donner un signal de gravite exploitable SANS
avoir besoin d'acceder au contenu verrouille/aux donnees elles-memes).

Deux familles de format constatees sur le corpus reel :
- Enregistrements : "10M+ Records", "16.20 M", "x10341 comptes", "22k Credit Card"
- Taille de donnees : "40gb of corporate data", "550GB", "1,7 GB"
value_masked porte la grandeur normalisee (nombre absolu d'enregistrements ou
d'octets) plutot que le texte brut matche, pour permettre un futur tri par
gravite sans reparser le texte."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

_UNIT_MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000, "b": 1_000_000_000}

# Nombre (avec , ou . comme separateur decimal) + suffixe K/M -- le suffixe
# seul (ex: "4K premium", resolution video) est trop ambigu pour un signal de
# gravite : on exige un mot de contexte confirmant qu'il s'agit d'un compte
# d'enregistrements, cherche APRES (ex: "10M+ Records") ou AVANT (ex:
# "LOG:PASS | 16.20 M", le format le plus frequent sur DARKNET ARMY, ou le
# mot de contexte precede le nombre plutot que le suivre) -- voir
# _has_record_context. re.IGNORECASE necessaire, "Records"/"LOG" apparaissent
# capitalises dans les titres reels du corpus.
_RECORD_COUNT_RE = re.compile(
    r"\b([0-9]+(?:[.,][0-9]+)?)\s?([kKmM])\+?\b", re.IGNORECASE
)

# Resolution video (4K, 8K...) immediatement suivie d'un mot de qualite video
# -- a exclure explicitement du pattern d'enregistrements, meme avec un mot de
# contexte ambigu a proximite (ex: titre "PREMIUM HITS 4K PREMIUM UHD" : "HITS"
# valide a raison X4 plus loin dans le meme titre, mais ne doit pas aussi
# valider ce "4K" qui designe une resolution, pas un volume). Se limite aux
# suffixes K courts (1-2 chiffres) : un vrai volume en K a 3+ chiffres avant
# suffixe ("22k Credit Card") n'entre jamais en collision avec une resolution.
_VIDEO_RESOLUTION_CONTEXT_RE = re.compile(
    r"^\d{1,2}k\s*(uhd|hd|premium|quality|resolution)", re.IGNORECASE
)

_RECORD_CONTEXT_WORDS = re.compile(
    r"records?|accounts?|comptes?|hits?|credentials?|logs?|lignes?|log|pass|url|combo"
    r"|cards?|users?|clients?|customers?|victims?|entries|rows?|leaks?",
    re.IGNORECASE,
)
_CONTEXT_WINDOW_CHARS = 20


def _has_record_context(text: str, match_start: int, match_end: int) -> bool:
    before = text[max(0, match_start - _CONTEXT_WINDOW_CHARS) : match_start]
    after = text[match_end : match_end + _CONTEXT_WINDOW_CHARS]
    return bool(
        _RECORD_CONTEXT_WORDS.search(before) or _RECORD_CONTEXT_WORDS.search(after)
    )


# "x10341", "X552" -- prefixe x/X directement suivi d'un nombre, format de
# comptage de comptes tres frequent sur ce corpus (forums de vente de comptes
# vole/leak). Pas besoin de mot de contexte ici : le "x" prefixe est deja le
# signal (peu de faux positifs constates -- une variable "x123" isolee dans du
# texte libre est rare).
_X_PREFIX_COUNT_RE = re.compile(r"\bx([0-9]{2,7})\b", re.IGNORECASE)

# Taille de donnees explicite -- uniquement les abreviations anglaises
# (GB/MB/TB), suffisamment specifiques pour ne pas avoir besoin de mot de
# contexte (peu de faux positifs constates sur ce corpus, contrairement a K/M
# seuls). Les abreviations francaises (Go/Mo/To) sont volontairement exclues :
# "To" collisionne avec le mot anglais tres courant "to" (constate
# empiriquement : "$1000 to avoid..." matchait comme "1000 To" = 1 petaoctet).
_DATA_SIZE_RE = re.compile(r"\b([0-9]+(?:[.,][0-9]+)?)\s?(gb|mb|tb)\b", re.IGNORECASE)

_SIZE_MULTIPLIERS = {
    "mb": 1_000_000,
    "gb": 1_000_000_000,
    "tb": 1_000_000_000_000,
}


def _parse_number(raw: str) -> float:
    # "16.20", "1,7" -- la virgule est un separateur decimal ici (constate sur
    # le corpus, ex: "1,7 GB"), pas un separateur de milliers.
    return float(raw.replace(",", "."))


def _record_match(count: int) -> RawMatch:
    return RawMatch(
        type=DetectionType.VOLUME,
        value_masked=f"{count:,} enregistrements".replace(",", " "),
        value_hash=hash_value(f"records:{count}"),
        validated=True,
    )


def find_volumes(text: str) -> list[RawMatch]:
    matches: list[RawMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for match in _RECORD_COUNT_RE.finditer(text):
        if _VIDEO_RESOLUTION_CONTEXT_RE.match(text[match.start() :]):
            continue
        if not _has_record_context(text, match.start(), match.end()):
            continue
        number_str, unit = match.groups()
        count = int(_parse_number(number_str) * _UNIT_MULTIPLIERS[unit.lower()])
        seen_spans.add(match.span())
        matches.append(_record_match(count))

    for match in _X_PREFIX_COUNT_RE.finditer(text):
        if any(match.start() >= s and match.end() <= e for s, e in seen_spans):
            continue
        seen_spans.add(match.span())
        matches.append(_record_match(int(match.group(1))))

    for match in _DATA_SIZE_RE.finditer(text):
        if match.span() in seen_spans:
            continue
        number_str, unit = match.groups()
        size_bytes = int(_parse_number(number_str) * _SIZE_MULTIPLIERS[unit.lower()])
        matches.append(
            RawMatch(
                type=DetectionType.VOLUME,
                value_masked=f"{size_bytes:,} octets".replace(",", " "),
                value_hash=hash_value(f"bytes:{size_bytes}"),
                validated=True,
            )
        )

    return matches
