"""Changements d'adresse des sources (2026-10-05).

Lecture : quiconque voit les sources (l'analyste doit savoir qu'une source a
basculé). Lancer une vérification, appliquer ou rejeter une candidate : admin,
comme toute écriture sur les sources.

Préfixe distinct de `/api/sources` : `/api/sources/{source_id}` capturerait
sinon « address-changes » comme un identifiant (422).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import exige_role, get_current_user, get_db
from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.db.models.source_address_change import SourceAddressChange
from app.db.models.user import User
from app.services import source_address_service as service

router = APIRouter(
    prefix="/api/source-addresses",
    tags=["sources"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class AddressChangeOut(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    old_url: str
    new_url: str
    origin: str
    status: str
    evidence: str | None
    reason: str | None
    parsed_victims: int | None
    common_victims: int | None
    detected_at: datetime
    last_checked_at: datetime
    applied_at: datetime | None
    decided_by: str | None


def _sortie(c: SourceAddressChange, nom: str) -> AddressChangeOut:
    return AddressChangeOut(
        id=c.id,
        source_id=c.source_id,
        source_name=nom,
        old_url=c.old_url,
        new_url=c.new_url,
        origin=c.origin,
        status=c.status,
        evidence=c.evidence,
        reason=c.reason,
        parsed_victims=c.parsed_victims,
        common_victims=c.common_victims,
        detected_at=c.detected_at,
        last_checked_at=c.last_checked_at,
        applied_at=c.applied_at,
        decided_by=c.decided_by,
    )


@router.get("", response_model=list[AddressChangeOut])
def lister(db: Session = Depends(get_db)) -> list[AddressChangeOut]:
    return [_sortie(c, nom) for c, nom in service.lister(db)]


class RunOut(BaseModel):
    task_id: str
    origin: str


@router.post(
    "/run",
    response_model=RunOut,
    status_code=202,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def lancer(origin: Literal["site", "deepdarkcti"]) -> RunOut:
    """Lance une passe tout de suite, sur la file dédiée (`links`)."""
    from app.worker.tasks.address_tasks import (
        check_addresses_deepdarkcti_task,
        check_addresses_sites_task,
    )

    tache = (
        check_addresses_sites_task
        if origin == "site"
        else check_addresses_deepdarkcti_task
    )
    return RunOut(task_id=str(tache.delay().id), origin=origin)


def _decision(fonction, change_id: uuid.UUID, db: Session, utilisateur: User):
    try:
        ligne = fonction(db, change_id, utilisateur.username)
    except service.AddressChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    noms = dict((c.id, n) for c, n in service.lister(db, limit=1000))
    return _sortie(ligne, noms.get(ligne.id, "?"))


@router.post(
    "/{change_id}/apply",
    response_model=AddressChangeOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def appliquer(
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> AddressChangeOut:
    return _decision(service.appliquer, change_id, db, utilisateur)


@router.post(
    "/{change_id}/reject",
    response_model=AddressChangeOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def rejeter(
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> AddressChangeOut:
    return _decision(service.rejeter, change_id, db, utilisateur)
