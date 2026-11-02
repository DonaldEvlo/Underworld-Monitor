"""Recherche de termes de la watchlist dans un texte deja collecte. Logique
pure (voir CONTRIBUTING.md). Precurseur simple de la couche `detect` complete
(patterns/registry).

Tolere deux formes d'obfuscation frequentes sur le dark web (constate
empiriquement sur les corpus type carding/leak-forum -- voir conversation
projet) :
  - leetspeak courant : l3ak, d4ta, hack3d, d0x (substitution chiffre/symbole
    <-> lettre visuellement proche)
  - espacement/tirets internes : "d a t a b a s e", "d-u-m-p" (technique pour
    passer sous des filtres de mots-cles naifs)

Ne couvre PAS : synonymes/traductions (geres en ajoutant le terme lui-meme a
la watchlist, pas par une regle generique), ni la casse (deja geree par
IGNORECASE)."""

from __future__ import annotations

import re
from functools import lru_cache

# Substitutions leetspeak vers la lettre visuellement proche -- direction
# lettre -> chiffres/symboles (utilisee pour construire, pour chaque lettre
# du terme watchlist, une classe de caracteres qui accepte la forme normale
# ET ses variantes obfusquees).
_LEET_VARIANTS: dict[str, str] = {
    "o": "o0",
    "e": "e3",
    "a": "a4",
    "i": "i1",
    "l": "l1",
    "s": "s5$",
    "t": "t7",
    "b": "b8",
    "g": "g9",
}

# Separateur optionnel tolere ENTRE deux lettres consecutives d'un terme (pas
# necessaire a l'interieur d'un mot deja separe par un espace naturel dans le
# terme original, ex: "data leak" -- seulement pour capter l'insertion
# artificielle type "d a t a b a s e" ou "d-u-m-p").
_SEPARATOR = r"[\s._-]{0,2}"


@lru_cache(maxsize=256)
def _compile_pattern(term: str) -> re.Pattern[str]:
    """Construit une regex qui matche `term` tel quel, ses variantes
    leetspeak lettre-par-lettre, et une insertion de separateurs entre
    lettres. Compile une seule fois par terme (@lru_cache) : la watchlist est
    courte et change rarement, pas la peine de recompiler a chaque document."""
    chars = term.lower()
    parts = []
    for idx, char in enumerate(chars):
        is_last = idx == len(chars) - 1

        if char.isalpha():
            variants = _LEET_VARIANTS.get(char, char)
            parts.append(f"[{re.escape(variants)}]")
        elif char == " ":
            # Un espace dans le terme original reste un vrai separateur de
            # mots (obligatoire), mais tolere aussi des separateurs
            # supplementaires de chaque cote (ex: "data  leak", "data-leak").
            parts.append(_SEPARATOR + r"\s" + _SEPARATOR)
        else:
            parts.append(re.escape(char))

        # Separateur optionnel APRES chaque lettre (jamais apres un espace
        # deja gere ci-dessus, ni apres le dernier caractere du terme) :
        # capte l'insertion type "d a t a b a s e".
        if char != " " and not is_last:
            parts.append(_SEPARATOR)

    pattern = r"\b" + "".join(parts) + r"\b"
    return re.compile(pattern, re.IGNORECASE)


def find_keyword_matches(text: str, keywords: list[str]) -> list[str]:
    """Retourne les termes de `keywords` presents dans `text` (forme normale,
    leetspeak, ou avec separateurs internes -- voir _compile_pattern)."""
    return [kw for kw in keywords if _compile_pattern(kw).search(text)]
