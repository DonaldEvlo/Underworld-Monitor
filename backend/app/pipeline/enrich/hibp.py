"""Corroboration d'un mot de passe via HIBP Pwned Passwords (k-anonymity).

Repond a "ce mot de passe apparait-il deja dans des fuites connues ?" -- un
credential dont le mot de passe est deja vu 10 000 fois est du recyclage sans
valeur ; un mot de passe inconnu de HIBP sur un domaine surveille est un
signal bien plus fort.

**k-anonymity : le mot de passe ne quitte JAMAIS le processus.** On calcule
le SHA-1 du clair en memoire, on n'envoie a HIBP que ses **5 premiers
caracteres hexadecimaux** (le "prefixe"), et l'API renvoie tous les suffixes
connus commencant par ce prefixe (~500 a 1000 entrees). La comparaison finale
se fait **localement**. HIBP ne peut donc pas savoir quel mot de passe a ete
teste -- c'est ce qui rend cette API compatible avec la regle 2 (jamais de PII
brute transmise), contrairement a l'API "Pwned Accounts" qui exigerait
d'envoyer une adresse email en clair et est donc **exclue de ce projet**.

**Deux hachages a ne pas confondre** (voir CONTRIBUTING.md §8) :
1. Le **SHA-1** calcule ici, uniquement pour interroger HIBP, jamais persiste
   ni logge. C'est le protocole impose par l'API, pas un choix de stockage.
2. Le **HMAC-SHA256 poivre** de `detect/masking.py::hash_password`, lui
   persiste, pour la correlation. Un SHA-1 (comme un SHA-256) nu est
   reversible par dictionnaire sur un mot de passe -- ne jamais le stocker.

Clearnet, hors Tor (reseau `backend`) : meme regime que crt.sh/IntelX, voir
CONTRIBUTING.md §2. HIBP interroge son propre index deja constitue, aucune requete
n'atteint l'infrastructure d'une entite surveillee.

API publique, **sans cle** pour Pwned Passwords (contrairement a l'API
"Pwned Accounts", payante) -- rien a ajouter a `.env`.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_RANGE_URL = "https://api.pwnedpasswords.com/range/"
_TIMEOUT_SECONDS = 15
# Longueur du prefixe imposee par l'API HIBP : 5 caracteres hex. Ne pas
# augmenter -- un prefixe plus long reduirait l'anonymat (moins de suffixes
# renvoyes, donc un ensemble de candidats plus etroit cote HIBP).
_PREFIX_LENGTH = 5


class HibpLookupError(Exception):
    """HIBP n'a pas repondu correctement (reseau, timeout, corps inexploitable)."""


@dataclass(frozen=True)
class PasswordBreachResult:
    """Verdict pour un mot de passe. Ne contient jamais le mot de passe ni son
    hash complet -- uniquement le prefixe deja transmis a HIBP (5 caracteres,
    non identifiant par construction) et le comptage."""

    prefix: str
    breach_count: int

    @property
    def is_breached(self) -> bool:
        return self.breach_count > 0


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _fetch_range(prefix: str) -> str:
    response = requests.get(
        f"{_RANGE_URL}{prefix}",
        headers={
            "User-Agent": "threat-intel-platform",
            # Elargit le jeu de reponses avec du bruit ajoute par HIBP :
            # anonymat renforce, sans changer le resultat apres filtrage local.
            "Add-Padding": "true",
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def _parse_suffix_counts(body: str, suffix: str) -> int:
    """Cherche `suffix` dans la reponse HIBP (`SUFFIXE:COMPTE` par ligne) et
    retourne son comptage, 0 s'il est absent.

    Les lignes de padding ajoutees par `Add-Padding` ont un compte de 0 et
    sont donc naturellement traitees comme "non trouve"."""
    for line in body.splitlines():
        line_suffix, _, count = line.strip().partition(":")
        if line_suffix.upper() != suffix:
            continue
        try:
            return int(count)
        except ValueError:
            raise HibpLookupError(
                "Reponse HIBP inexploitable (comptage non numerique)"
            ) from None
    return 0


def check_password(password: str) -> PasswordBreachResult:
    """Interroge HIBP sur `password` par k-anonymity et retourne son comptage
    d'apparitions dans des fuites connues.

    `password` est le mot de passe EN CLAIR, en memoire uniquement : il n'est
    ni logge, ni persiste, ni transmis -- seuls les 5 premiers caracteres de
    son SHA-1 quittent le processus. L'appelant ne doit jamais conserver ce
    clair au-dela de l'appel (voir services/password_breach_service.py)."""
    if not password:
        raise HibpLookupError("Mot de passe vide")

    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:_PREFIX_LENGTH], digest[_PREFIX_LENGTH:]

    try:
        body = _fetch_range(prefix)
    except requests.RequestException as exc:
        raise HibpLookupError(f"HIBP injoignable : {exc}") from exc

    return PasswordBreachResult(
        prefix=prefix, breach_count=_parse_suffix_counts(body, suffix)
    )
