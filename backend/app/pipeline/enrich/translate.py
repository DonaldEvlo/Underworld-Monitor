"""Traduction de contenu collecte vers le francais ou l'anglais, a la demande
(bouton dans le panneau detail document) -- jamais dans le chemin critique de
collecte, voir CONTRIBUTING.md.

Modeles Helsinki-NLP/opus-mt-XX-YY convertis au format ctranslate2 pour
l'inference (rapide, CPU -- voir app/scripts/convert_translation_model.py).
L'encodage/decodage passe neanmoins par MarianTokenizer (transformers), pas par
sentencepiece brut : les modeles Marian appliquent une normalisation de
ponctuation (Moses, via sacremoses) avant le decoupage en tokens. Sans elle,
le decoupage ne correspond plus a ce que le modele a vu a l'entrainement et la
generation degenere en boucles de repetition (constate empiriquement, pas une
precaution theorique -- voir l'historique de ce fichier). Charges paresseusement
et mis en cache par paire de langues.

Quand aucun modele direct source->cible n'existe (ex: ru->fr), on pivote par
l'anglais (ru->en puis en->fr) : Helsinki-NLP ne publie pas toutes les paires
directement, l'anglais est presque toujours disponible comme intermediaire.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import ctranslate2
from transformers import MarianTokenizer

from app.core.config import settings

PIVOT_LANGUAGE = "en"

# Dossier du modele Helsinki-NLP/opus-mt-mul-en (toutes langues -> anglais),
# repli quand aucune paire dediee n'existe. Installe par
# `python -m app.scripts.convert_translation_model mul en`.
MULTILINGUAL_SOURCE = "mul"

# Un modele n'est utilisable que complet : poids ET tokenizer.
_REQUIRED_FILES = ("model.bin", "source.spm", "target.spm", "vocab.json")

# opus-mt (Marian) encode des positions absolues jusqu'a 512 -- au-dela,
# ctranslate2 leve un RuntimeError plutot que de tronquer. Mais bien avant
# cette limite technique, regrouper plusieurs phrases dans un meme chunk fait
# deja decrocher le modele : constate empiriquement, un chunk de ~280 tokens
# mais melangeant plusieurs phrases (titre + plusieurs paragraphes) produit une
# sortie qui omet silencieusement des pans entiers du texte source (le beam
# search "abandonne" avant d'avoir tout couvert, sans erreur ni troncature
# signalee). Traduire phrase par phrase evite ce decrochage -- chaque phrase
# testee individuellement jusqu'a ~65 tokens reste fidele et complete. La
# limite ci-dessous n'est donc qu'un filet de securite pour les phrases
# anormalement longues (sans ponctuation), pas le mecanisme de decoupage
# principal (une phrase = un chunk, voir _split_into_chunks).
MAX_TOKENS_PER_CHUNK = 100

# Coupe apres un signe de ponctuation terminale (. ! ? et equivalents russes,
# suivi d'espace/fin de ligne) : separateur qui degrade le moins le sens du
# texte source lors du regroupement en chunks, contrairement a une coupe par
# nombre de caracteres qui peut trancher au milieu d'une phrase.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


class TranslationUnavailableError(Exception):
    """Aucun modele (direct ou via pivot) n'est disponible pour cette paire."""


class _LanguagePairModel:
    def __init__(self, model_dir: Path):
        self._translator = ctranslate2.Translator(str(model_dir), device="cpu")
        self._tokenizer = MarianTokenizer.from_pretrained(str(model_dir))

    def _token_count(self, text: str) -> int:
        return len(self._tokenizer(text)["input_ids"])

    def _split_into_chunks(self, text: str) -> list[str]:
        """Une phrase de `text` = un chunk (voir MAX_TOKENS_PER_CHUNK : regrouper
        plusieurs phrases fait decrocher le modele, qui omet silencieusement une
        partie du texte source). Seule exception : une phrase seule qui depasse
        deja la limite de securite est re-decoupee grossierement par nombre de
        mots (mieux vaut une coupure arbitraire qu'un chunk trop long)."""
        sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
        if not sentences:
            return [text] if text.strip() else []

        chunks: list[str] = []
        for sentence in sentences:
            if self._token_count(sentence) <= MAX_TOKENS_PER_CHUNK:
                chunks.append(sentence)
                continue
            words = sentence.split()
            start = 0
            while start < len(words):
                end = start + 1
                while (
                    end < len(words)
                    and self._token_count(" ".join(words[start : end + 1]))
                    <= MAX_TOKENS_PER_CHUNK
                ):
                    end += 1
                chunks.append(" ".join(words[start:end]))
                start = end
        return chunks

    def _translate_chunk(self, text: str) -> str:
        input_ids = self._tokenizer(text)["input_ids"]
        tokens = self._tokenizer.convert_ids_to_tokens(input_ids)
        results = self._translator.translate_batch([tokens])
        output_ids = self._tokenizer.convert_tokens_to_ids(results[0].hypotheses[0])
        return self._tokenizer.decode(output_ids, skip_special_tokens=True)

    def translate(self, text: str) -> str:
        """Traduit `text` en un minimum de blocs (jamais phrase par phrase ou
        ligne par ligne : trop peu de contexte fait degenerer le modele en
        repetitions, voir _split_into_chunks). Les sauts de ligne du texte
        source sont remplaces par des espaces avant traduction : impossible de
        les preserver exactement puisque plusieurs lignes sont fusionnees dans
        un meme chunk pour garder assez de contexte."""
        if not text.strip():
            return text
        normalized = re.sub(r"\s+", " ", text).strip()
        return " ".join(
            self._translate_chunk(chunk)
            for chunk in self._split_into_chunks(normalized)
        )


@lru_cache(maxsize=16)
def _load_pair(source_lang: str, target_lang: str) -> _LanguagePairModel | None:
    model_dir = Path(settings.TRANSLATION_MODELS_DIR) / f"{source_lang}-{target_lang}"
    # ⚠️ Les poids ne suffisent pas : sans tokenizer, `MarianTokenizer` leve a
    # chaque appel. Constate le 2026-09-21 sur `mul-en`, converti a moitie
    # (poids presents, tokenizer absent) : le verifier sur `model.bin` seul
    # faisait passer un modele inutilisable pour installe. Un dossier
    # incomplet est traite comme ABSENT -- l'appelant dit alors « aucun
    # modele », au lieu d'une erreur interne.
    if not all((model_dir / name).exists() for name in _REQUIRED_FILES):
        return None
    return _LanguagePairModel(model_dir)


def is_pair_available(source_lang: str, target_lang: str) -> bool:
    return _load_pair(source_lang, target_lang) is not None


def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """Traduit `text` de `source_lang` vers `target_lang` (codes ISO 639-1, ex:
    "ru", "en", "fr"). Pivote par l'anglais si aucun modele direct n'existe.

    Leve `TranslationUnavailableError` si aucun chemin (direct ou via pivot)
    n'est disponible -- l'appelant (endpoint API) traduit ca en 503/400 explicite
    plutot que de laisser une KeyError remonter."""
    if source_lang == target_lang:
        return text

    direct = _load_pair(source_lang, target_lang)
    if direct is not None:
        return direct.translate(text)

    if source_lang != PIVOT_LANGUAGE:
        # Modele dedie d'abord (meilleure qualite), sinon le modele
        # MULTILINGUE vers l'anglais.
        #
        # ⚠️ Ajoute le 2026-09-21, signale a l'usage pendant l'annotation sur
        # une annonce EXILIO404 en portugais : seules les paires ru-en et en-fr
        # etaient installees, et 6 documents de l'echantillon de reference
        # (pt, it, sk, bg) restaient illisibles. Un modele par langue ne se
        # justifie pas pour quelques documents ; `opus-mt-mul-en` les couvre
        # tous, au prix d'une qualite moindre -- suffisante pour comprendre de
        # quoi parle une annonce, pas pour la citer.
        to_pivot = _load_pair(source_lang, PIVOT_LANGUAGE) or _load_pair(
            MULTILINGUAL_SOURCE, PIVOT_LANGUAGE
        )
        if to_pivot is not None:
            en_anglais = to_pivot.translate(text)
            if target_lang == PIVOT_LANGUAGE:
                return en_anglais
            from_pivot = _load_pair(PIVOT_LANGUAGE, target_lang)
            if from_pivot is not None:
                return from_pivot.translate(en_anglais)

    raise TranslationUnavailableError(
        f"Aucun modele de traduction disponible pour {source_lang} -> {target_lang}"
    )
