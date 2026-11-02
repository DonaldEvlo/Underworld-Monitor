"""Detection d'IBAN dans un texte. Logique pure (voir CONTRIBUTING.md).

Le pattern seul (code pays + chiffres + alphanumerique) matche des faux
positifs (identifiants techniques, references de commande) : c'est
validators.iban_is_valid (mod-97) qui confirme, meme principe que card.py."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_iban
from app.pipeline.detect.raw_match import RawMatch
from app.pipeline.detect.validators import iban_is_valid

# Code pays (2 lettres) + cle de controle (2 chiffres) + jusqu'a 30 caracteres
# alphanumeriques (longueur max reelle d'un IBAN, ex: Malte). Espaces optionnels
# tous les 4 caracteres, format d'ecriture le plus courant dans un texte libre.
_IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[A-Z0-9]{1,4}){2,7}\b")


def find_ibans(text: str) -> list[RawMatch]:
    matches = []
    for match in _IBAN_RE.finditer(text):
        raw = match.group(0)
        cleaned = raw.replace(" ", "").upper()
        if not (15 <= len(cleaned) <= 34):
            continue
        if not iban_is_valid(cleaned):
            continue
        matches.append(
            RawMatch(
                type=DetectionType.IBAN,
                value_masked=mask_iban(cleaned),
                value_hash=hash_value(cleaned),
                validated=True,
            )
        )
    return matches
