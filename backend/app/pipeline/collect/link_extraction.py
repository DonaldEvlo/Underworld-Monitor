"""Extraction passive de liens et detection de contenu verrouille dans le
texte d'un document collecte (post de forum, message...).

Volontairement PASSIF : ce module ne fait jamais de requete vers les URLs
qu'il trouve. Il se contente de les reperer dans du texte deja collecte, pour
qu'un analyste humain puisse ensuite decider -- via l'UI -- d'ajouter l'une
d'elles comme nouvelle `Source` a part entiere (voir POST /api/sources).
Suivre automatiquement ces liens transformerait le collecteur en crawler
recursif non borne, ce qui sort du principe "une source = une decision
explicite" du projet (voir CONTRIBUTING.md)."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Bruit frequent en fin de match (ponctuation de phrase collee a l'URL) --
# jamais des caracteres qui pourraient faire partie d'un chemin legitime.
_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"

# Signatures textuelles des murs "reagir/repondre pour voir" rencontres sur
# DARKNET ARMY (addon LFS) et d'autres forums XenForo utilisant le meme addon
# de contenu verrouille. Verification manuelle du cas reel avant d'ajouter un
# nouveau motif -- pas de generalisation speculative.
_LOCKED_CONTENT_MARKERS = (
    "to see this hidden content",
    "reply & react",
    "reply and react",
)


def extract_mentioned_urls(text: str, *, exclude_url: str | None = None) -> list[str]:
    """Repere les URLs http(s) mentionnees dans `text`, dedupliquees en
    conservant l'ordre d'apparition. `exclude_url` (typiquement l'URL du fil
    lui-meme, deja dans `RawDocumentContract.url`) est omis pour ne pas lister
    une source comme "lien mentionne" dans son propre document."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if exclude_url and url == exclude_url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def is_content_locked(text: str) -> bool:
    """Detecte si le texte capture est un texte d'accroche derriere un mur
    "reagir/repondre pour voir le contenu" plutot que le contenu reel du post
    -- signal a propager vers l'analyste (source_meta.content_locked) plutot
    que de laisser croire que la collecte a tout capture."""
    lowered = text.lower()
    return any(marker in lowered for marker in _LOCKED_CONTENT_MARKERS)
