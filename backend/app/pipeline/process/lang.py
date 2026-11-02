"""Detection de la langue du contenu collecte. Logique pure (voir CONTRIBUTING.md).

Reutilise langdetect (deja une dependance pour la traduction a la demande,
voir enrich/translate.py) plutot que d'ajouter une lib dediee -- suffisant
pour du texte de plusieurs phrases comme celui collecte ici, pas besoin de
fasttext/CLD3 pour ce volume."""

from langdetect import LangDetectException, detect


def detect_language(text: str) -> str | None:
    """Retourne le code de langue ISO 639-1 (ex: "ru", "en") de `text`, ou
    None si indetectable (texte trop court, vide, ou uniquement des symboles/
    URLs -- ca arrive sur certains posts XSSF reduits a une image + un lien)."""
    if not text or not text.strip():
        return None
    try:
        return detect(text)
    except LangDetectException:
        return None
