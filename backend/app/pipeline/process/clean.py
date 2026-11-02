"""Nettoyage du texte brut collecte, avant detect/enrich. Logique pure, sans
dependance DB/Celery (voir CONTRIBUTING.md, principes d'architecture).

Cible les irritants constates sur le corpus reel (voir conversation projet) :
- images markdown residuelles (`![](/storage/posts/...)`) frequentes sur xssf,
  qui ne portent aucune information textuelle et bruitent le matching de mots-cles.
- espaces/retours a la ligne multiples issus de l'extraction HTML->texte.
Ne touche PAS a la ponctuation ni a la casse : `detect` (patterns regex) et le
matching de mots-cles ont besoin du texte le plus proche possible de l'original.
"""

import re

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MULTIPLE_SPACES_RE = re.compile(r"[ \t]+")
_MULTIPLE_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Nettoie `text` pour la suite du pipeline. Idempotent (appliquer deux
    fois donne le meme resultat) -- important car `detect` pourrait tourner
    sur du contenu deja nettoye lors d'un reprocessing."""
    cleaned = _MARKDOWN_IMAGE_RE.sub("", text)
    cleaned = _MULTIPLE_SPACES_RE.sub(" ", cleaned)
    cleaned = _MULTIPLE_BLANK_LINES_RE.sub("\n\n", cleaned)
    lines = [line.strip() for line in cleaned.split("\n")]
    return "\n".join(lines).strip()
