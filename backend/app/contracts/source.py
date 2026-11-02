from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class SourceType(str, Enum):
    ONION = "onion"
    PASTE = "paste"
    TELEGRAM = "telegram"
    FORUM = "forum"


class SourceContract(BaseModel):
    model_config = {"extra": "forbid"}

    id: UUID
    name: str
    type: SourceType
    url: str
    active: bool = True
    # Certains sites (ex: forums avec file d'attente anti-bot type Dread) exigent
    # l'exécution de JS pour passer un écran d'attente/défi avant le contenu réel —
    # un simple client HTTP (TorScraper) ne peut structurellement pas les franchir.
    # Ce flag route la collecte vers PlaywrightScraper (navigateur réel, proxifié
    # Tor) avec un délai étendu, au lieu du fetch HTTP direct.
    requires_js: bool = False
    last_collected_at: datetime | None = None
    created_at: datetime
