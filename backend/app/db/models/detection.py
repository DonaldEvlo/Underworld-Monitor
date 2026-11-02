import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Detection(Base):
    """Une occurrence de pattern PII detectee dans un RawDocument (voir
    pipeline/detect/registry.py). Jamais de valeur brute stockee (regle non
    negociable, voir CONTRIBUTING.md) -- uniquement value_masked/value_hash."""

    __tablename__ = "detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_documents.id"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    value_masked: Mapped[str] = mapped_column(String, nullable=False)
    # Index (pas unique) : plusieurs detections distinctes peuvent legitimement
    # partager le meme hash (meme secret leake dans deux documents differents) --
    # c'est precisement ce que le hash permet de correler, voir masking.py.
    value_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # True si le document source matche la watchlist active au moment de la
    # collecte (voir registry.detect_all, keyword_match.py) -- distingue une
    # fuite pertinente pour une organisation surveillee d'une detection
    # technique correcte mais hors sujet.
    is_relevant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    # Corroboration par un second observateur independant (RansomLook, voir
    # pipeline/enrich/ransomlook_corroboration.py). NULL = jamais confronte ;
    # ne jamais interpreter un NULL comme « non corrobore », c'est une
    # absence de mesure, pas un resultat negatif.
    corroboration_status: Mapped[str | None] = mapped_column(String, index=True)
    # Gang attribue par RansomLook. Interet reel : pour une victime que nos
    # collecteurs DLS ne couvrent pas, c'est la seule attribution disponible.
    corroborated_group: Mapped[str | None] = mapped_column(String)
    corroborated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lien PUBLIC citable justifiant la corroboration (page /group/<gang>
    # de RansomLook, ou la victime figure -- verifie le 2026-08-26).
    # Complementaire de raw_documents.url, qui est un .onion exigeant Tor.
    corroboration_evidence_url: Mapped[str | None] = mapped_column(String)
    # Migration 0024 (corroboration par victime, 2026-09-11) :
    # TOUS les gangs qui revendiquent la victime, celui de notre source en
    # premier -- une double revendication est une information.
    corroborated_groups: Mapped[list | None] = mapped_column(JSONB)
    # « domain » ou « name » : comment la victime a ete rapprochee. Un
    # rapprochement par raison sociale n'est accepte que dans l'historique du
    # gang de la source.
    corroboration_match: Mapped[str | None] = mapped_column(String)
    # Date d'indexation la plus ancienne chez un observateur : mesure notre
    # avance (ou notre retard) sur l'agregateur.
    corroboration_first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Migration 0025 (second observateur, 2026-09-15) : QUELS observateurs
    # tiers ont vu la victime (`ransomlook`, `ransomware_live`) -- pas un gang.
    # L'union augmente la couverture ; « exclusive » = aucun.
    corroboration_observers: Mapped[list | None] = mapped_column(JSONB)

    # Severite de la detection ELLE-MEME (voir
    # services/detection_severity_service.py, migration 0015) -- distincte de
    # `alerts.severity`, qui n'existe que pour une entite surveillee. C'est ce
    # qui permet a une institution hors perimetre de porter une severite sans
    # declencher d'alerte.
    # NULL = pas encore evaluee (ou type non matchable), jamais « aucune ».
    severity: Mapped[str | None] = mapped_column(String, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
