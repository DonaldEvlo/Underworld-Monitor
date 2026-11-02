"""Detection de numeros de telephone dans un texte. Logique pure (voir
CONTRIBUTING.md).

Pas de validateur checksum (un numero de telephone n'en a pas, contrairement
a card/iban) : la plage de longueur (E.164 : 8 a 15 chiffres apres le +) est
le seul filtre disponible. Volontairement centre sur le format international
(+ obligatoire) plutot qu'un format local ambigu (ex: 10 chiffres qui peut
etre un numero de suivi de colis, un ID de transaction...) -- bien moins de
faux positifs, au prix de rater les numeros locaux ecrits sans indicatif."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_generic
from app.pipeline.detect.raw_match import RawMatch

# +indicatif suivi de 7 a 14 chiffres (espaces/points/tirets optionnels entre
# groupes) -- couvre l'essentiel des formats d'ecriture internationaux courants.
_PHONE_RE = re.compile(r"\+[1-9][0-9]{0,3}(?:[ .-]?[0-9]){6,14}\b")


def find_phones(text: str) -> list[RawMatch]:
    matches = []
    for match in _PHONE_RE.finditer(text):
        raw = match.group(0)
        digits = "".join(c for c in raw if c.isdigit())
        if not (8 <= len(digits) <= 15):
            continue
        matches.append(
            RawMatch(
                type=DetectionType.PHONE,
                value_masked=mask_generic(raw),
                value_hash=hash_value(digits),
                validated=False,
            )
        )
    return matches
