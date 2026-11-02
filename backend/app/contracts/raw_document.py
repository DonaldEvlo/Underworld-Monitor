from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.contracts.source import SourceType


class RawDocumentContract(BaseModel):
    """Sortie unique de la couche `collect`, quel que soit le fetcher utilisé.

    Le collecteur ne "comprend" rien : il capture proprement pour que
    process/detect/classify aient toute la matière. `content`/`content_hash`
    sont le minimum vital ; `title`/`published_at`/`author`/`source_meta`
    sont remplis quand le collecteur les a deja sous la main (evite un
    re-parsing en aval) mais restent optionnels -- tous les collecteurs ne
    peuvent pas tous les fournir.

    Volontairement absents d'ici (voir discussion projet) :
    - signaux de menace (type de donnees, volume, prix...) : c'est le travail
      de detect/enrich sur `content`, pas de collect.
    - metadonnees OPSEC de la requete (statut HTTP, UA, circuit Tor...) : en
      logs structures au moment de la collecte, pas dans ce contrat qui
      remonte jusqu'a l'alerting.
    """

    model_config = {"extra": "forbid"}

    id: UUID
    source_id: UUID
    url: str
    content: str
    content_hash: str
    fetched_at: datetime
    simhash: int | None = None
    language: str | None = None
    is_duplicate: bool = False

    # Routage + reproductibilite
    source_type: SourceType
    collector: str
    collector_version: str

    # Signal de contenu fortement recommande
    published_at: datetime | None = None
    title: str | None = None
    author: str | None = None

    # Brut, pour re-parser si l'extracteur evolue -- pas toujours disponible
    # (ex: Akira/XSSF exposent du JSON deja structure, pas une page HTML par
    # document individuel).
    raw_html: str | None = None

    # Champs propres au type de source (thread_id, views, data_link Akira,
    # paste_id...). Choix pragmatique : dict libre plutot que des sous-modeles
    # types par source_type, pour ne pas bloquer sur un schema qui n'a pas
    # encore assez d'exemples reels pour se figer -- a durcir plus tard si le
    # besoin de validation stricte se confirme.
    source_meta: dict[str, Any] | None = None
