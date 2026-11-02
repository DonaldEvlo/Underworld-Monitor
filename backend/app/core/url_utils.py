"""Normalisation d'URL pour comparaison de doublons entre sources.

Deux sources qui pointent vers la meme adresse ne doivent pas pouvoir
coexister meme si elles different par le schema (http/https) ou un slash
final -- cas reel constate : DREAD enregistre deux fois (`http://dready...
.onion` et `https://dready....onion/`)."""

from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    """Reduit une URL a `hote(minuscules) + chemin(sans slash final)`, en
    ignorant le schema. Suffisant pour detecter les doublons "meme adresse,
    ponctuation differente" sans etre une normalisation RFC 3986 complete."""
    candidate = url.strip()
    if "//" not in candidate:
        candidate = f"//{candidate}"
    parsed = urlparse(candidate)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"
