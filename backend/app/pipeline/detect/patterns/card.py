"""Detection de numeros de carte bancaire dans un texte. Logique pure (voir
CONTRIBUTING.md).

Le pattern seul (13-19 chiffres, espaces/tirets optionnels) matche enormement
de faux positifs (ID de commande, numeros de telephone concatenes, timestamps
Unix...) : c'est validators.luhn_is_valid qui coupe l'essentiel du bruit,
voir CONTRIBUTING.md section detection ("chaque detection est validee avant
stockage pour couper les faux positifs a la source")."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_card
from app.pipeline.detect.raw_match import RawMatch
from app.pipeline.detect.validators import luhn_is_valid

# 13 a 19 chiffres (plage reelle des reseaux carte : Visa/Mastercard 16,
# Amex 15, certaines cartes 13 ou 19), groupes de 4 separes par espace/tiret
# optionnel -- format le plus courant tel qu'ecrit dans un texte libre.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def find_cards(text: str) -> list[RawMatch]:
    matches = []
    for match in _CARD_RE.finditer(text):
        raw = match.group(0)
        digits = "".join(c for c in raw if c.isdigit())
        if not (13 <= len(digits) <= 19):
            continue
        if not luhn_is_valid(digits):
            continue
        matches.append(
            RawMatch(
                type=DetectionType.CARD,
                value_masked=mask_card(digits),
                value_hash=hash_value(digits),
                validated=True,
            )
        )
    return matches
