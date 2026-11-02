"""Detection du groupe d'attaquants revendiquant une compromission. Logique
pure (voir CONTRIBUTING.md).

Cinquieme detecteur de la famille "exploiter ce que la source declare". Sur un
agregateur de leak sites, chaque annonce porte le nom du groupe qui la publie
(voir pipeline/collect/ransomlook/adapter.py, marqueur "Groupe:" + metadonnee
`group_name`) -- une revendication publique, pas une attribution que la
plateforme deduirait elle-meme.

Complementaire des autres detecteurs de la famille :
- victim.py repond a "qui est touche ?"
- announcement.py a "de quoi s'agit-il ?"
- celui-ci a "**qui revendique ?**"

Portee et limite : c'est une revendication *declaree* par l'acteur lui-meme sur
son propre site de fuite, jamais une attribution verifiee. A traiter comme tel
cote analyste (meme regime que les TTPs evoques dans CONTRIBUTING.md : "declared,
unverified"). `validated=True` porte donc sur "la source declare bien ce
groupe", pas sur "ce groupe est bien l'auteur".

Pas une PII : un nom de gang ransomware est un identifiant d'acteur malveillant
public, jamais une donnee personnelle a proteger -- value_masked reste en clair
(meme raisonnement que patterns/domain.py)."""

from __future__ import annotations

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

# Marqueur pose par les adaptateurs d'agregateurs de leak sites en tete de
# `content` (voir collect/ransomlook/adapter.py). Ancre en debut de ligne pour
# ne jamais capturer le mot "Groupe:" cite au fil d'une description.
_GROUP_LINE_RE = re.compile(r"^Groupe:\s*(?P<group>.+?)\s*$", re.MULTILINE)

# Un nom de groupe exploitable contient au moins un caractere alphanumerique
# latin et n'est pas une forme triviale. Seuil bas : certains noms sont tres
# courts ("8base", "3AM").
_HAS_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_MIN_LENGTH = 2
_MAX_LENGTH = 60


def find_threat_actors(text: str) -> list[RawMatch]:
    """Retourne les groupes d'attaquants declares dans `text`.

    Dedup par nom normalise : un document agregeant plusieurs annonces d'un
    meme groupe ne doit produire qu'une detection."""
    matches = []
    seen: set[str] = set()

    for match in _GROUP_LINE_RE.finditer(text):
        value = " ".join(match.group("group").split()).strip()
        if not _MIN_LENGTH <= len(value) <= _MAX_LENGTH:
            continue
        if not _HAS_ALNUM_RE.search(value):
            continue
        dedup_key = value.casefold()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        matches.append(
            RawMatch(
                type=DetectionType.THREAT_ACTOR,
                value_masked=value,
                value_hash=hash_value(dedup_key),
                validated=True,
            )
        )

    return matches
