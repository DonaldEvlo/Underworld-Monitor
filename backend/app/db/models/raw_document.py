import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Index (pas unique) : la dedup exacte se decide en couche process/repo,
    # pas via une contrainte DB -- un meme contenu peut legitimement reapparaitre
    # sur des sources differentes.
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    source_type: Mapped[str] = mapped_column(String, nullable=False)
    collector: Mapped[str] = mapped_column(String, nullable=False)
    collector_version: Mapped[str] = mapped_column(String, nullable=False)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String)
    raw_html: Mapped[str | None] = mapped_column(Text)
    source_meta: Mapped[dict | None] = mapped_column(JSONB)

    # BigInteger (pas Integer) : l'empreinte SimHash tient sur 63 bits, voir
    # pipeline/process/dedup.py -- un Integer (32 bits) deborderait.
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    language: Mapped[str | None] = mapped_column(String)
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Precurseur simple de la couche detect (voir pipeline/detect/keyword_match.py) :
    # calcule et fige a la collecte, pas recalcule a la lecture -- la watchlist
    # peut changer apres coup sans qu'on veuille reecrire l'historique.
    matched_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Classification de l'annonce (voir detect/announcement_filter.py).
    # NULL = jamais classe -- ne PAS lire comme « non pertinent ».
    # `noise` = hors perimetre (tutoriel, entraide, jeu pirate) : le document
    # reste en base mais ne doit ni alimenter la watchlist ni compter dans le
    # calcul de gravite.
    announcement_class: Mapped[str | None] = mapped_column(String, index=True)
    announcement_score: Mapped[int | None] = mapped_column(Integer)
    # Motif lisible : un analyste doit comprendre POURQUOI un document a ete
    # ecarte sans relire le code.
    announcement_reason: Mapped[str | None] = mapped_column(String)

    # Verdict LLM sur les annonces que les REGLES n'ont pas su trancher
    # (migration 0018). Colonnes separees : `announcement_class` n'est jamais
    # ecrase, les regles restent maitresses du chemin critique.
    #
    # NULL = pas encore soumis au LLM, ou soumis sans reponse exploitable --
    # jamais « le LLM n'a pas su ». Ce dernier cas s'ecrit `uncertain`, qui est
    # un verdict a part entiere.
    llm_class: Mapped[str | None] = mapped_column(String, index=True)
    llm_reason: Mapped[str | None] = mapped_column(String)
    # Sans le nom du modele, un verdict n'est pas auditable.
    llm_model: Mapped[str | None] = mapped_column(String)
    llm_classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Vrai quand le forum n'expose qu'un apercu (93 documents sur 93 sur
    # BreachForums). Un score faible signifie alors « pas pu juger », pas
    # « pas une fuite ».
    content_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
