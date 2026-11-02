"""Une entree de planification : quelle action, a quel moment.

Depuis la migration 0021, cette table est la SOURCE DE VERITE de Celery Beat
(voir `worker/db_scheduler.py`) : ajouter, modifier ou supprimer une entree
prend effet sans toucher au code ni recreer le service `beat`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ⚠️ Cle unique technique, tenue egale au `label`. Elle porte la contrainte
    # d'unicite heritee de la migration 0020 : deux entrees ne peuvent pas
    # porter le meme nom, ce qui evite deux lignes indiscernables dans
    # l'interface.
    task_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Nom lisible, choisi par l'analyste (« Collecte du matin »).
    label: Mapped[str] = mapped_column(String, nullable=False)
    # ⚠️ Action a executer, contrainte a une LISTE BLANCHE (voir
    # services/scheduled_task_service.KNOWN_ACTIONS). Un nom libre reviendrait
    # a offrir l'execution de n'importe quelle tache Celery enregistree a un
    # utilisateur authentifie.
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Champs crontab, au format que Celery accepte tel quel : "6,18", "*/15",
    # "*". Les stocker en texte evite de reinventer un analyseur.
    cron_minute: Mapped[str] = mapped_column(String, nullable=False, default="0")
    cron_hour: Mapped[str] = mapped_column(String, nullable=False, default="*")
    cron_day_of_week: Mapped[str] = mapped_column(String, nullable=False, default="*")
    # File Celery. Determinee par l'action (une tache longue a la sienne), pas
    # librement choisie : la mettre sur la mauvaise file bloquerait l'alerting.
    queue: Mapped[str] = mapped_column(String, nullable=False, default="celery")

    # ⚠️ Suspendre n'empeche pas Beat de declencher quand l'entree existe :
    # l'ordonnanceur filtre sur ce drapeau, et la tache le verifie aussi. Les
    # deux, parce qu'une entree peut etre suspendue entre deux rechargements de
    # l'ordonnanceur.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "success" | "error" | "skipped". `skipped` distingue une tache suspendue
    # d'une tache en echec -- un booleen confondrait les deux.
    last_status: Mapped[str | None] = mapped_column(String)
    last_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    last_detail: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
