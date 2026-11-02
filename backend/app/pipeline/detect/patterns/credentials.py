r"""Detection de couples identifiant:mot de passe (format combolist) dans un
texte. Logique pure (voir CONTRIBUTING.md).

Un pattern naif type `[a-zA-Z0-9_]+:\S+` matche quasiment toute ligne "Cle: valeur" d'un
document structure (constate empiriquement sur ce corpus : ~96% des documents
matchent un `x:y` generique, essentiellement des faux positifs -- "Section:
NEWS", "Date: 2026-...", timestamps). On se limite donc au format le plus
specifique et le moins ambigu : email:mot_de_passe, la forme la plus repandue
dans les vrais combolists/leaks de credentials."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_password, mask_generic
from app.pipeline.detect.raw_match import RawMatch

# email:mot_de_passe -- le ":" doit etre immediatement colle a l'email (pas de
# "Contact: john@ex.com" avec espace, qui n'est pas un couple credentials) et
# suivi d'au moins 4 caracteres sans espace (mot de passe plausible).
_EMAIL_PASSWORD_RE = re.compile(
    r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}):([^\s:]{4,})\b"
)


def find_credentials(text: str) -> list[RawMatch]:
    """Detecte les couples email:mot_de_passe.

    `value_hash` porte le **HMAC poivre du mot de passe seul** (voir
    masking.hash_password), pas un SHA-256 du couple entier. Deux raisons :
    - **Securite** : un mot de passe a une entropie faible, un SHA-256 nu est
      reversible par dictionnaire (voir hash_password). Le couple entier
      n'etait pas mieux protege -- l'email qu'il contient est devinable.
    - **Correlation** : hacher le couple rendait deux occurrences du meme mot
      de passe (sur des comptes differents) incomparables, alors que c'est
      precisement le signal recherche -- un mot de passe reutilise, ou deja
      present dans des fuites connues (voir pipeline/enrich/hibp.py).

    Le mot de passe en clair ne quitte jamais cette fonction : ni retourne, ni
    logge, seul son HMAC et le couple masque sortent."""
    matches = []
    for match in _EMAIL_PASSWORD_RE.finditer(text):
        pair = match.group(0)
        password = match.group(2)
        matches.append(
            RawMatch(
                type=DetectionType.CREDENTIALS,
                value_masked=mask_generic(pair),
                value_hash=hash_password(password),
                validated=False,
            )
        )
    return matches
