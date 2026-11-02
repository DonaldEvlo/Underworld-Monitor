import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertAccess(Base):
    """Journal des ACCES aux alertes -- exigence de la regle 5 (« minimisation
    & tracabilite »), qui n'avait jusqu'ici AUCUNE implementation.

    ⚠️ Ce qu'on journalise et pourquoi : une alerte porte des valeurs masquees
    et l'adresse de la page ou elles ont ete lues. Savoir QUI a consulte QUOI
    et QUAND est ce qui distingue un outil de veille d'un depot de donnees
    fuitees. Sans ce journal, la regle 5 etait une intention.

    ⚠️ ON JOURNALISE L'ACCES, PAS LE CONTENU. La ligne ne porte ni valeur, ni
    extrait, ni domaine : seulement un utilisateur, une alerte, une action et
    un horodatage. Journaliser le contenu consulte recreerait une seconde
    copie de la PII qu'on s'interdit de stocker (regle 2) -- le journal
    deviendrait le probleme qu'il documente.

    ⚠️ Pas d'adresse IP : le poste est interne et identifie par le compte.
    En ajouter une serait de la donnee personnelle supplementaire sans usage
    etabli, contraire a la minimisation de la meme regle 5.
    """

    __tablename__ = "alert_accesses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ⚠️ `ON DELETE SET NULL`, et NON une cle etrangere stricte. La premiere
    # version interdisait de SUPPRIMER un compte des qu'il avait consulte une
    # alerte (migration 0028) : l'intention -- ne pas effacer la trace --
    # etait bonne, le moyen faux. La trace survit parce que `username` et
    # `role` sont recopies ci-dessous ; c'est cette copie qui rend le
    # detachement possible sans perte.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # `list` | `read` | `report` | `export` -- ce qui a ete fait, jamais ce qui
    # a ete vu.
    action: Mapped[str] = mapped_column(String, nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )
