import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoldAnnotation(Base):
    """Un document de l'echantillon de reference, et le jugement humain porte
    sur lui.

    C'est l'etalon contre lequel on mesure les regles, le LLM et le modele.
    Sans lui, toutes les metriques du projet mesuraient l'ACCORD entre
    classifieurs, jamais leur JUSTESSE.

    ⚠️ AUCUN VERDICT DE CLASSIFIEUR N'EST STOCKE ICI COMME REFERENCE. On garde
    `sampled_verdict` (le verdict des regles AU MOMENT DU TIRAGE) uniquement
    parce qu'il definit la strate, donc les poids de redressement. A
    l'evaluation, les regles sont REJOUEES sur le document : c'est ce qui
    permet de mesurer une correction de regle contre la meme reference, sans
    jamais re-annoter.

    ⚠️ Rien de ce qui est ici n'est affiche pendant l'annotation, a l'exception
    du document lui-meme : voir le verdict orienterait le jugement, et la
    reference perdrait sa valeur."""

    __tablename__ = "gold_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Ordre de presentation, melange : ne jamais grouper par strate.
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Ordre DIFFERENT pour la seconde passe, NULL hors sous-ensemble de controle.
    control_rank: Mapped[int | None] = mapped_column(Integer)

    # Strate de tirage, ex. `forum:noise` ou `victim_site:leak`.
    stratum: Mapped[str] = mapped_column(String, nullable=False)
    # Taille de la strate DANS LE CORPUS au moment du tirage : c'est elle qui
    # permet de redresser les estimations (l'echantillon sur-represente
    # volontairement `noise`, ou se joue l'erreur la plus couteuse).
    stratum_population: Mapped[int] = mapped_column(Integer, nullable=False)
    sampled_verdict: Mapped[str] = mapped_column(String, nullable=False)

    # `leak` | `noise` | `uncertain` -- NULL tant que non annote.
    label: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text)
    annotated_by: Mapped[str | None] = mapped_column(String)
    annotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Seconde passe, a l'aveugle de la premiere : mesure la COHERENCE de
    # l'annotateur (kappa de Cohen). Une reference dont on ignore la fiabilite
    # ne vaut pas grand-chose comme etalon.
    control_label: Mapped[str | None] = mapped_column(String)
    control_annotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
