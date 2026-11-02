"""Gestion des collectes automatiques : ajouter, modifier, supprimer.

Depuis la migration 0021, la table `scheduled_tasks` est la source de verite de
Celery Beat (voir `worker/db_scheduler.py`) : ces routes changent reellement le
calendrier, sans recreer le service `beat`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.services import scheduled_task_service as service
from app.services.scheduled_task_service import KNOWN_ACTIONS, ScheduleError
from app.worker.db_scheduler import SCHEDULE_RELOAD_SECONDS

router = APIRouter(
    prefix="/api/schedules",
    tags=["schedules"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class ActionOut(BaseModel):
    model_config = {"extra": "forbid"}

    action: str
    label: str
    queue: str
    description: str


class ScheduleOut(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    label: str
    action: str
    action_label: str
    # File imposee par l'action, jamais choisie : une tache longue placee sur la
    # file par defaut bloquerait la collecte ET l'alerting.
    queue: str
    cron_minute: str
    cron_hour: str
    cron_day_of_week: str
    schedule: str
    enabled: bool
    last_run_at: datetime | None
    # "success" | "error" | "skipped". `skipped` = suspendue au declenchement,
    # a ne pas confondre avec un echec.
    last_status: str | None
    last_duration_seconds: int | None
    last_detail: str | None


class SchedulesResponse(BaseModel):
    model_config = {"extra": "forbid"}

    schedules: list[ScheduleOut]
    actions: list[ActionOut]
    # Delai maximal avant qu'un changement soit pris en compte par Beat.
    # Affiche tel quel : un reglage qui semble sans effet pendant une minute
    # ferait douter l'analyste de son action.
    reload_delay_seconds: int = SCHEDULE_RELOAD_SECONDS


class ScheduleCreate(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=120)
    action: str
    cron_minute: str = "0"
    cron_hour: str = "*"
    cron_day_of_week: str = "*"
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    label: str | None = Field(default=None, max_length=120)
    action: str | None = None
    cron_minute: str | None = None
    cron_hour: str | None = None
    cron_day_of_week: str | None = None
    enabled: bool | None = None


def _to_out(tache) -> ScheduleOut:
    meta = KNOWN_ACTIONS.get(tache.action, {})
    return ScheduleOut(
        id=tache.id,
        label=tache.label,
        action=tache.action,
        action_label=meta.get("label", tache.action),
        queue=tache.queue,
        cron_minute=tache.cron_minute,
        cron_hour=tache.cron_hour,
        cron_day_of_week=tache.cron_day_of_week,
        schedule=service.describe_schedule(tache),
        enabled=tache.enabled,
        last_run_at=tache.last_run_at,
        last_status=tache.last_status,
        last_duration_seconds=tache.last_duration_seconds,
        last_detail=tache.last_detail,
    )


def _charger(db: Session, task_id: uuid.UUID):
    tache = service.get(db, task_id)
    if tache is None:
        raise HTTPException(status_code=404, detail="Planification introuvable")
    return tache


@router.get("", response_model=SchedulesResponse)
def list_schedules(db: Session = Depends(get_db)) -> SchedulesResponse:
    """Collectes automatiques et actions disponibles."""
    return SchedulesResponse(
        schedules=[_to_out(t) for t in service.list_tasks(db)],
        actions=[
            ActionOut(
                action=nom,
                label=meta["label"],
                queue=meta["queue"],
                description=meta["description"],
            )
            for nom, meta in KNOWN_ACTIONS.items()
        ],
    )


@router.post(
    "",
    response_model=ScheduleOut,
    status_code=201,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def create_schedule(
    payload: ScheduleCreate, db: Session = Depends(get_db)
) -> ScheduleOut:
    """Ajoute un moment de collecte.

    ⚠️ `action` est validee contre une liste blanche : l'interface ne peut pas
    programmer une tache Celery arbitraire.
    """
    try:
        return _to_out(service.create(db, **payload.model_dump()))
    except ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/{task_id}",
    response_model=ScheduleOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def update_schedule(
    task_id: uuid.UUID, payload: ScheduleUpdate, db: Session = Depends(get_db)
) -> ScheduleOut:
    """Modifie un moment de collecte (horaire, action, nom, activation)."""
    tache = _charger(db, task_id)
    try:
        return _to_out(service.update(db, tache, **payload.model_dump()))
    except ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# `response_model=None` est obligatoire : sans lui, FastAPI deduit le modele
# de reponse de l'annotation `-> None` et refuse de demarrer, un 204 ne
# pouvant pas porter de corps.
@router.delete(
    "/{task_id}",
    status_code=204,
    response_model=None,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_schedule(task_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """Supprime un moment de collecte.

    ⚠️ Definitif : l'amorcage par defaut ne recree les entrees que si la table
    est ENTIEREMENT vide, une suppression ne sera donc pas annulee au prochain
    demarrage de `beat`.
    """
    service.delete(db, _charger(db, task_id))
