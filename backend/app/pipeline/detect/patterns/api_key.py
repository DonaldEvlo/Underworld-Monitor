"""Detection de cles API/tokens a prefixe reconnaissable dans un texte.
Logique pure (voir CONTRIBUTING.md).

Contrairement a un token generique (chaine alphanumerique longue -- bien trop
ambigu, ca matche des hashes, des ID de session, du base64 quelconque), ces
prefixes sont specifiques a un fournisseur et rendent le pattern fiable sans
validateur dedie. Liste volontairement limitee aux formats les plus repandus
(OpenAI, AWS, GitHub, Slack, Stripe) -- a etendre au cas par cas si le corpus
reel en revele d'autres, pas besoin de couvrir tous les fournisseurs existants
d'emblee."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_generic
from app.pipeline.detect.raw_match import RawMatch

_PATTERNS = {
    "openai": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe_key": re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{24,}\b"),
}


def find_api_keys(text: str) -> list[RawMatch]:
    matches = []
    for pattern in _PATTERNS.values():
        for match in pattern.finditer(text):
            value = match.group(0)
            matches.append(
                RawMatch(
                    type=DetectionType.API_KEY,
                    value_masked=mask_generic(value),
                    value_hash=hash_value(value),
                    validated=True,
                )
            )
    return matches
