"""Enumeration de sous-domaines connus d'un domaine surveille, a la demande
(bouton sur la fiche entite) -- jamais dans le chemin critique de collecte,
voir CONTRIBUTING.md. Enrichissement clearnet (reseau `backend`, pas Tor) : voir
CONTRIBUTING.md §2 pour la justification de cette exception et son perimetre
volontairement limite (noms de domaine uniquement, jamais de donnee
d'exposition -- ports, bannieres, CVE -- voir CONTRIBUTING.md §1).

Deux sources, passives par construction (interrogent des certificats deja
emis et publics, aucune requete n'atteint l'infrastructure du domaine
surveille) :
- **crt.sh** (source principale) -- essayee en premier.
- **certspotter** (SSLMate, fallback) -- crt.sh s'est revele instable en
  usage reel (502/timeout/404 intermittents constates empiriquement, y
  compris en production sur un domaine reel -- pas specifique a un domaine
  ou a un environnement de dev, l'infra crt.sh elle-meme est sous tension
  par intermittence). certspotter sert de secours quand crt.sh echoue apres
  son propre retry, plutot que de laisser l'analyste sans resultat."""

from __future__ import annotations

import re

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

_CRT_SH_URL = "https://crt.sh/"
_CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
_TIMEOUT_SECONDS = 15

# Un certificat wildcard produit un CN/SAN du type "*.exemple.sn" -- le
# prefixe "*." est retire pour ne garder que la forme comparable a un
# selecteur `domain` (voir contracts/entity.py, pipeline/alerting/matching.py).
_WILDCARD_PREFIX_RE = re.compile(r"^\*\.")


class SubdomainLookupError(Exception):
    """Aucune des sources n'est joignable ou n'a renvoye une reponse exploitable."""


def _normalize_domain(value: str) -> str:
    return _WILDCARD_PREFIX_RE.sub("", value.strip().lower().rstrip("."))


def _is_subdomain_of(candidate: str, domain: str) -> bool:
    """True si `candidate` est `domain` lui-meme ou un vrai sous-domaine (memes
    labels terminaux) -- meme regle que pipeline/alerting/matching.py, jamais
    un `contains` sur la chaine brute (voir CONTRIBUTING.md §8)."""
    candidate_labels = candidate.split(".")
    domain_labels = domain.split(".")
    if len(candidate_labels) < len(domain_labels):
        return False
    return candidate_labels[-len(domain_labels) :] == domain_labels


def _retry_config():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )


@_retry_config()
def _fetch_crtsh(normalized_domain: str) -> requests.Response:
    response = requests.get(
        _CRT_SH_URL,
        params={"q": f"%.{normalized_domain}", "output": "json"},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _from_crtsh(normalized_domain: str) -> set[str]:
    response = _fetch_crtsh(normalized_domain)

    # crt.sh renvoie parfois un corps vide (200 OK) plutot qu'un tableau JSON
    # vide quand aucun certificat n'est trouve -- traite comme "aucun resultat",
    # pas comme une erreur.
    if not response.text.strip():
        return set()

    try:
        entries = response.json()
    except ValueError as exc:
        raise SubdomainLookupError(
            "Reponse crt.sh inexploitable (JSON invalide)"
        ) from exc

    found: set[str] = set()
    for entry in entries:
        # name_value peut contenir plusieurs noms separes par des retours
        # ligne (SAN multiples sur un meme certificat).
        for name in entry.get("name_value", "").splitlines():
            candidate = _normalize_domain(name)
            if candidate:
                found.add(candidate)
    return found


@_retry_config()
def _fetch_certspotter(normalized_domain: str) -> requests.Response:
    response = requests.get(
        _CERTSPOTTER_URL,
        params={
            "domain": normalized_domain,
            "include_subdomains": "true",
            "expand": "dns_names",
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _from_certspotter(normalized_domain: str) -> set[str]:
    response = _fetch_certspotter(normalized_domain)

    try:
        entries = response.json()
    except ValueError as exc:
        raise SubdomainLookupError(
            "Reponse certspotter inexploitable (JSON invalide)"
        ) from exc

    # `include_subdomains=true` fait aussi remonter des domaines partageant
    # un meme certificat SAN sans lien avec le domaine cherche (ex: un SAN
    # multi-marques incluant "operateur.sn" ET "operateur.cd") -- le filtre par
    # labels (_is_subdomain_of) ecarte ce bruit, pas seulement l'exclusion du
    # domaine lui-meme.
    found: set[str] = set()
    for entry in entries:
        for name in entry.get("dns_names", []):
            candidate = _normalize_domain(name)
            if candidate:
                found.add(candidate)
    return found


def find_subdomains(domain: str) -> list[str]:
    """Retourne les sous-domaines de `domain` observes dans des certificats
    publics, tries et deduppliques. `domain` lui-meme est exclu du resultat
    (deja connu -- voir contracts/entity.py, ce n'est pas une decouverte).

    Essaie crt.sh en premier ; si crt.sh reste en echec apres son propre
    retry, bascule sur certspotter avant d'abandonner. Ne leve que si les
    deux sources ont echoue."""
    normalized_domain = _normalize_domain(domain)

    try:
        found = _from_crtsh(normalized_domain)
    except (requests.RequestException, SubdomainLookupError) as crtsh_error:
        try:
            found = _from_certspotter(normalized_domain)
        except (requests.RequestException, SubdomainLookupError) as certspotter_error:
            raise SubdomainLookupError(
                f"crt.sh injoignable ({crtsh_error}) et certspotter injoignable ({certspotter_error})"
            ) from certspotter_error

    subdomains = {
        candidate
        for candidate in found
        if candidate != normalized_domain
        and _is_subdomain_of(candidate, normalized_domain)
    }
    return sorted(subdomains)
