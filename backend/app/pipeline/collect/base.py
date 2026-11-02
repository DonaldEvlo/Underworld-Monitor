import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract


class Collector(ABC):
    """Interface commune à tous les collecteurs de la couche 1.

    Chaque implémentation (onion, paste, telegram, ...) transforme une source
    en une liste de `RawDocumentContract`, indépendamment du moyen de
    récupération (Tor, navigateur automatisé, API).
    """

    # A definir par chaque sous-classe -- sert au champ `collector` du
    # contrat (reproductibilite : savoir quelle logique a produit un
    # document donne). `COLLECTOR_VERSION` a incrementer quand la logique
    # d'extraction change de façon a pouvoir distinguer d'anciens documents
    # produits par une version differente du parsing.
    COLLECTOR_NAME: str = "unknown"
    COLLECTOR_VERSION: str = "1"

    @abstractmethod
    def collect(self, source: SourceContract) -> list[RawDocumentContract]: ...

    def _build_document(
        self,
        source: SourceContract,
        url: str,
        content: str,
        *,
        title: str | None = None,
        published_at: datetime | None = None,
        author: str | None = None,
        raw_html: str | None = None,
        source_meta: dict[str, Any] | None = None,
    ) -> RawDocumentContract:
        return RawDocumentContract(
            id=uuid.uuid4(),
            source_id=source.id,
            url=url,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            fetched_at=datetime.now(timezone.utc),
            source_type=source.type,
            collector=self.COLLECTOR_NAME,
            collector_version=self.COLLECTOR_VERSION,
            title=title,
            published_at=published_at,
            author=author,
            raw_html=raw_html,
            source_meta=source_meta,
        )
