"""Validateurs qui confirment ou rejettent un match de pattern regex, pour
couper les faux positifs a la source (voir CONTRIBUTING.md, section detection).
Un pattern seul (ex: 16 chiffres) matche enormement de faux positifs (ID de
commande, numero de telephone concatene...) ; la validation checksum est ce
qui distingue un vrai numero de carte/IBAN d'une suite de chiffres au hasard.
"""


def luhn_is_valid(digits: str) -> bool:
    """Algorithme de Luhn (mod 10) -- utilise par toutes les cartes bancaires
    (Visa, Mastercard, Amex...) pour detecter les erreurs de saisie. `digits`
    doit deja etre nettoye (uniquement des chiffres, voir patterns/card.py)."""
    if not digits.isdigit():
        return False
    total = 0
    for i, char in enumerate(reversed(digits)):
        d = int(char)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_IBAN_LETTER_OFFSET = 55  # ord('A') - 10 : conversion lettre -> chiffre (A=10..Z=35)


def iban_is_valid(iban: str) -> bool:
    """Validation mod-97 (ISO 7064) : les 4 premiers caracteres (pays + cle de
    controle) sont deplaces a la fin, les lettres converties en chiffres
    (A=10..Z=35), le tout doit etre congru a 1 modulo 97. `iban` doit deja etre
    nettoye (majuscules, sans espaces, voir patterns/iban.py)."""
    if len(iban) < 8 or not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False

    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        str(ord(c) - _IBAN_LETTER_OFFSET) if c.isalpha() else c for c in rearranged
    )
    if not numeric.isdigit():
        return False
    return int(numeric) % 97 == 1
