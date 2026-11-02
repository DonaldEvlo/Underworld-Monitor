"""Detection d'adresses de wallet crypto (Bitcoin, Ethereum) dans un texte.
Logique pure (voir CONTRIBUTING.md).

Pas de validateur checksum ici contrairement a card.py/iban.py : Ethereum n'a
aucune checksum embarquee dans l'adresse (juste un format hexadecimal fixe),
et implementer la checksum Base58Check de Bitcoin pour si peu de gain (le
format seul filtre deja bien, les faux positifs restants sont rares sur du
texte libre) n'est pas justifie pour ce premier lot -- a ajouter plus tard si
le taux de faux positifs observe en usage le justifie."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_generic
from app.pipeline.detect.raw_match import RawMatch

# Bitcoin : legacy (1...), P2SH (3...), Bech32 (bc1...).
_BTC_RE = re.compile(r"\b(?:bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
# Ethereum (et toute chaine EVM-compatible) : 0x + 40 hex.
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")


def find_crypto_wallets(text: str) -> list[RawMatch]:
    matches = []
    for pattern in (_BTC_RE, _ETH_RE):
        for match in pattern.finditer(text):
            value = match.group(0)
            matches.append(
                RawMatch(
                    type=DetectionType.CRYPTO_WALLET,
                    value_masked=mask_generic(value),
                    value_hash=hash_value(value),
                    validated=False,
                )
            )
    return matches
