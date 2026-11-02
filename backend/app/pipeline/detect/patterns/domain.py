"""Detection de noms de domaine (clearnet et .onion) mentionnes dans un texte.
Logique pure (voir CONTRIBUTING.md).

Contrairement aux autres patterns (email, card, iban...), un domaine n'est pas
une PII a proprement parler -- c'est un indicateur de renseignement (une autre
source a surveiller, un site mentionne comme mirror/cible). value_masked reste
donc lisible en clair (voir mask_domain) : un domaine n'a pas besoin
d'anonymat fort comme un email/une carte, et le masquer inutilement (constate
empiriquement sur des domaines courts type "ibb.co") rend la detection
inutilisable pour l'analyste sans proteger personne."""

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value, mask_domain
from app.pipeline.detect.raw_match import RawMatch

# Domaine .onion v3 (56 caracteres base32) -- le v2 (16 caracteres) est
# deprecie/retire du reseau Tor, plus la peine de le matcher.
_ONION_RE = re.compile(r"\b[a-z2-7]{56}\.onion\b")

# Domaine clearnet generique (2+ labels). Volontairement permissif sur les
# labels pour couvrir les sous-domaines -- le filtrage fiable se fait sur le
# TLD (liste blanche ci-dessous), pas ici.
_CLEARNET_DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,24}\b"
)

# Liste blanche des TLD reels les plus courants -- une liste noire de mots a
# exclure (.sys, .add, .archives...) s'est revelee un jeu du chat et de la
# souris sans fin (constate empiriquement : noms de fichiers Windows type
# "Pagefile.sys", code source "arrayList.add(...)", fin de phrase suivie d'un
# mot capitalise ".Add torrent..." matchaient tous comme domaine). Une liste
# blanche coupe tout ca d'un coup, au prix de rater un TLD reel absent d'ici
# (rare sur ce type de corpus -- a completer si constate en usage).
# Regroupement geographique par ligne : black eclaterait cette liste en un TLD
# par ligne (~110 lignes) et la rendrait illisible, d'ou le fmt: off.
# fmt: off
_TLD_ALLOWLIST = {
    "com", "org", "net", "io", "co", "me", "to", "xyz", "info", "biz",
    "ru", "su", "ua", "by", "kz",
    "de", "fr", "uk", "nl", "ch", "it", "es", "pl", "se", "no", "fi", "be", "at", "pt", "cz", "ro", "gr", "hu",
    "us", "ca", "br", "mx", "ar",
    "cn", "jp", "kr", "in", "id", "sg", "hk", "tw",
    # Afrique de l'Ouest / Maghreb / Afrique centrale -- cas d'usage cible de
    # la plateforme. Leur absence rendait le produit muet sur son propre
    # perimetre : aucune detection possible sur un domaine type "operateur.sn",
    # alors que le matching aval (matching.py) le supporte et est teste.
    "sn", "ci", "ml", "bf", "ne", "tg", "bj", "gn", "gw", "cv", "mr", "gm", "sl", "lr", "ng", "gh",
    "ma", "dz", "tn", "ly", "eg",
    "cm", "ga", "cg", "cd", "td", "cf", "gq",
    "za", "ke", "tz", "ug", "rw", "bi", "et", "mg", "mu", "sc", "ao", "mz", "zm", "zw", "bw", "na",
    "gov", "edu", "mil", "int",
}
# fmt: on


def _is_real_tld(value: str) -> bool:
    return value.rsplit(".", 1)[-1] in _TLD_ALLOWLIST


def find_domains(text: str) -> list[RawMatch]:
    matches = []
    seen: set[str] = set()

    for match in _ONION_RE.finditer(text):
        value = match.group(0).lower()
        if value in seen:
            continue
        seen.add(value)
        matches.append(
            RawMatch(
                type=DetectionType.DOMAIN,
                value_masked=mask_domain(value),
                value_hash=hash_value(value),
                validated=True,
            )
        )

    for match in _CLEARNET_DOMAIN_RE.finditer(text):
        value = match.group(0).lower()
        if value in seen or value.endswith(".onion") or not _is_real_tld(value):
            continue
        seen.add(value)
        matches.append(
            RawMatch(
                type=DetectionType.DOMAIN,
                value_masked=mask_domain(value),
                value_hash=hash_value(value),
                validated=False,
            )
        )

    return matches
