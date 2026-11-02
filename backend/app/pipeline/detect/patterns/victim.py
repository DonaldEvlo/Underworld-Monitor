"""Extraction du nom de l'organisation VICTIME annoncee sur un site de fuite
(leak site de groupe ransomware). Logique pure (voir CONTRIBUTING.md).

Difference fondamentale avec patterns/organization.py (NER spaCy) : ici le nom
n'est pas infere, il est **declare explicitement** par la source elle-meme.
Les sites de leak publient une annonce par victime, dont le nom est le titre de
l'annonce -- le collecteur le capture deja tel quel (voir
pipeline/collect/akira/adapter.py, `title=leak.name`, repris en tete de
`content` sous la forme "Victime: <nom>").

Consequence sur la fiabilite : `validated=True`, contrairement au NER qui reste
a False. Ce n'est pas une probabilite de modele, c'est une donnee structuree
lue a l'endroit ou la source l'a mise. C'est le signal le plus fiable du corpus
pour repondre a "quelles organisations sont touchees" -- 680 victimes distinctes
sur 687 annonces Akira collectees, la ou le NER, sur les memes documents, fait
remonter en tete du bruit ("Vuze, Utorrent" et "Transmission", clients
BitTorrent d'un boilerplate de telechargement, 524 occurrences chacun).

Comme DOMAIN/ORGANIZATION, un nom d'organisation victime n'est pas une PII :
c'est un indicateur de renseignement (l'entite touchee), pas une donnee a
proteger -- value_masked reste en clair (voir patterns/domain.py pour le meme
raisonnement).

Perimetre volontairement etroit : ce detecteur ne matche que le marqueur
explicite pose par le collecteur, jamais une heuristique sur du texte libre. Un
autre site de leak dont le collecteur produirait le meme marqueur serait couvert
sans changement ici ; un site sans marqueur ne produit simplement rien (pas de
faux positif invente)."""

from __future__ import annotations

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

# Marqueurs poses par les adaptateurs de collecte de leak sites en tete de
# `content`. Deux libelles coexistent : "Victime:" (voir
# pipeline/collect/akira/adapter.py) et "Victime annoncee:" (voir
# pipeline/collect/ransomlook/adapter.py, agregateur multi-groupes). Ancres en
# debut de ligne (re.MULTILINE + ^) pour ne jamais capturer une occurrence du
# mot citee au milieu d'une description d'annonce.
_VICTIM_LINE_RE = re.compile(
    r"^Victime(?:\s+annoncee)?:\s*(?P<name>.+?)\s*$", re.MULTILINE
)

# Meme garde-fou que patterns/organization.py : une raison sociale exploitable
# contient au moins une lettre latine et n'est pas une forme triviale.
_HAS_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_MIN_LENGTH = 3


def find_victims(text: str) -> list[RawMatch]:
    """Retourne les organisations victimes explicitement declarees dans `text`.

    Une annonce = une victime : la dedup par nom normalise evite qu'un document
    agregeant plusieurs annonces ne produise deux fois la meme organisation."""
    matches = []
    seen: set[str] = set()

    for match in _VICTIM_LINE_RE.finditer(text):
        value = " ".join(match.group("name").split()).strip()
        if len(value) < _MIN_LENGTH:
            continue
        if not _HAS_LATIN_LETTER_RE.search(value):
            continue
        dedup_key = value.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        matches.append(
            RawMatch(
                type=DetectionType.ORGANIZATION,
                value_masked=value,
                # Hash sur la forme normalisee, comme organization.py : deux
                # graphies du meme nom vues sur des annonces differentes doivent
                # se regrouper (voir DetectionRepository.top_organization_candidates).
                value_hash=hash_value(dedup_key),
                # Declare par la source, pas infere -- voir docstring module.
                validated=True,
            )
        )

    return matches
