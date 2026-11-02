"""Detection d'adresses email dans un texte. Logique pure (voir CONTRIBUTING.md)."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_email
from app.pipeline.detect.raw_match import RawMatch

# Volontairement simple (pas de regex RFC 5322 complete, notoirement illisible
# et sujette a false positives sur ce type de corpus) : suffisant pour repartir
# un email plausible d'un texte libre, quitte a laisser passer de rares formats
# exotiques (utile pour capturer, pas pour valider a 100% -- il n'y a pas de
# checksum pour un email comme pour une carte/IBAN).
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")


def find_emails(text: str) -> list[RawMatch]:
    matches = []
    for match in _EMAIL_RE.finditer(text):
        value = match.group(0)
        # Hash sur la forme normalisee (minuscule) : "Michelle.comi@..." et
        # "michelle.comi@..." sont la meme adresse en pratique (constate
        # empiriquement -- un meme email repete avec une casse differente
        # produisait deux detections distinctes au lieu d'une seule).
        # value_masked garde la forme originale pour l'affichage.
        matches.append(
            RawMatch(
                type=DetectionType.EMAIL,
                value_masked=mask_email(value),
                value_hash=hash_value(value.lower()),
                validated=False,
            )
        )
    return matches
