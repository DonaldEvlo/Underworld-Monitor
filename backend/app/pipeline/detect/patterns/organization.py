"""Detection de noms d'organisation mentionnes en texte libre (NER), sans
domaine ni email associe. Logique pure (voir CONTRIBUTING.md).

Contrairement aux autres patterns, ce detecteur ne repose pas sur une regex
mais sur un modele NER (spaCy, `en_core_web_sm`) : il infere qu'une chaine de
caracteres designe une organisation a partir du contexte de la phrase, il ne
la "reconnait" pas via un format fixe. D'ou `validated=False` systematique
(voir contracts/detection.py) -- ce n'est jamais confirme par un validateur
deterministe comme Luhn/mod-97, seulement une probabilite.

Comme DOMAIN (voir patterns/domain.py), un nom d'organisation n'est pas une
PII : c'est un indicateur de renseignement (une entite potentiellement
touchee), pas une donnee a proteger. value_masked reste donc en clair.

Limite assumee : `en_core_web_sm` est un modele anglophone. Le corpus reel
(forums/pastes dark web) est majoritairement en anglais, mais une mention
purement en russe ou en francais peut echapper au NER (angle mort documente,
meme logique que la _TLD_ALLOWLIST de domain.py -- a elargir si constate en
usage plutot qu'en anticipation)."""

from __future__ import annotations

import re
from functools import lru_cache

import spacy

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

_SPACY_MODEL_NAME = "en_core_web_sm"

# Formes trop courtes pour etre exploitables -- bruit frequent du NER (sigles
# tronques, ponctuation isolee happee dans une entite ORG). Un vrai nom
# d'organisation exploitable fait rarement moins de 3 caracteres.
_MIN_LENGTH = 3

# Un nom d'organisation exploitable contient au moins une lettre latine.
# Sans ce filtre, l'art ASCII/braille (mise en page frequente sur les forums
# dark web, ex: "⡀⠀⠀⠀⠀⠀⠀") ressort massivement comme "ORG" -- spaCy classe ces
# blocs de symboles Unicode comme des entites nommees faute de mieux, constate
# empiriquement sur le corpus reel (majorite des candidats sur un run initial).
_HAS_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

# REGLE NON NEGOCIABLE (CONTRIBUTING.md §2) : une entite NER peut englober une adresse
# email complete ("jean.dupont@exemple.com" classe ORG par spaCy, constate en
# test d'integration). value_masked etant stocke en clair pour ce type (un nom
# d'organisation n'est pas une PII), cela persistait l'adresse brute en base --
# court-circuitant mask_email applique par patterns/email.py sur la meme valeur.
# Toute forme ressemblant a une adresse est donc rejetee : l'email est de toute
# facon deja detecte, masque, par son propre detecteur.
_LOOKS_LIKE_EMAIL_RE = re.compile(r"\S+@\S+")

# Apostrophe typographique (U+2019) ramenee a l'apostrophe ASCII avant
# comparaison a _EXCLUDED_TERMS : sans ca "NDA’s" passait le filtre alors que
# "nda" est exclu (constate en base -- 8 detections pour cette seule graphie).
_TYPOGRAPHIC_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'"})

# Vocabulaire frequemment mal classifie ORG par spaCy sur ce corpus (acronymes
# techniques ou de champs de donnees, boutons d'interface, titres de section,
# noms de logiciels grand public). Constate empiriquement en base, pas
# anticipe : ces termes ne designent jamais une organisation surveillable.
#
# Cas particulier "vuze, utorrent" / "transmission" : boilerplate d'un pied de
# page explicatif repete sur ~500 pages d'un meme site de leak (524 detections
# chacun, soit les deux valeurs les plus frequentes du corpus, tres loin devant
# toute vraie organisation). Ce sont des clients BitTorrent cites dans une
# notice de telechargement, aucun rapport avec une victime.
_EXCLUDED_TERMS = {
    # acronymes de champs de donnees / documents
    "nda",
    "nda's",
    "dob",
    "ssn",
    "dni",
    "social security numbers",
    "passports",
    "password",
    # formes juridiques seules (sans raison sociale, non identifiantes)
    "llc",
    "llp",
    "pllc",
    "inc",
    "ltd",
    # acronymes techniques
    "isp",
    "ram",
    "cpu",
    "ssh",
    "sms",
    "apt",
    "ems",
    "ip address",
    # interface / navigation de forum
    "register",
    "reply & react",
    "download - click",
    "house",
    # clients BitTorrent cites dans un boilerplate de telechargement
    "vuze, utorrent",
    "transmission",
    "utorrent",
    "vuze",
}


@lru_cache(maxsize=1)
def _load_model():
    return spacy.load(_SPACY_MODEL_NAME, disable=["parser", "lemmatizer"])


def find_organizations(text: str) -> list[RawMatch]:
    nlp = _load_model()
    doc = nlp(text)

    matches = []
    seen: set[str] = set()

    for ent in doc.ents:
        if ent.label_ != "ORG":
            continue
        # Casse normalisee pour la dedup intra-texte : spaCy peut retourner
        # "Telco" et "TELCO" comme deux entites distinctes dans le meme
        # document. La casse d'origine est gardee pour l'affichage
        # (value_masked), seule la cle de dedup est normalisee.
        value = " ".join(ent.text.split()).strip()
        if len(value) < _MIN_LENGTH:
            continue
        if not _HAS_LATIN_LETTER_RE.search(value):
            continue
        if _LOOKS_LIKE_EMAIL_RE.search(value):
            continue
        dedup_key = value.lower()
        if dedup_key in seen:
            continue
        if dedup_key.translate(_TYPOGRAPHIC_APOSTROPHES) in _EXCLUDED_TERMS:
            continue
        seen.add(dedup_key)
        matches.append(
            RawMatch(
                type=DetectionType.ORGANIZATION,
                value_masked=value,
                value_hash=hash_value(dedup_key),
                validated=False,
            )
        )

    return matches
