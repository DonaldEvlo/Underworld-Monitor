"""Echantillon de reference : annotation humaine et evaluation.

Ouvert a l'analyste et a l'administrateur : juger une annonce demande de voir
le document, donc le perimetre `corpus`. Seul le TIRAGE est reserve a
l'administrateur -- il fixe l'etalon, et ne se refait jamais.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import exige_role, get_current_user, get_db
from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.db.models.user import User
from app.services import gold_service
from app.services.gold_service import GoldError

router = APIRouter(
    prefix="/api/gold",
    tags=["gold"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class LabelIn(BaseModel):
    model_config = {"extra": "forbid"}

    phase: str
    label: str
    note: str | None = None


def _refus(exc: GoldError) -> HTTPException:
    # 409 : la requete est valide, c'est l'etat de l'echantillon qui s'y oppose.
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/progress")
def get_progress(db: Session = Depends(get_db)) -> dict:
    return gold_service.progress(db)


@router.post(
    "/sample",
    status_code=201,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def post_sample(db: Session = Depends(get_db)) -> dict:
    try:
        return gold_service.build_sample(db)
    except GoldError as exc:
        raise _refus(exc) from exc


@router.get("/item")
def get_item(
    phase: str = "main", position: int | None = None, db: Session = Depends(get_db)
) -> dict | None:
    try:
        return gold_service.get_item(db, phase, position)
    except GoldError as exc:
        raise _refus(exc) from exc


@router.post("/item/{annotation_id}/translate")
def post_translate(annotation_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    try:
        return gold_service.translate_item(db, annotation_id)
    except GoldError as exc:
        raise _refus(exc) from exc


@router.patch("/item/{annotation_id}")
def put_label(
    annotation_id: uuid.UUID,
    payload: LabelIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return gold_service.record(
            db,
            annotation_id,
            phase=payload.phase,
            label=payload.label,
            note=payload.note,
            username=user.username,
        )
    except GoldError as exc:
        raise _refus(exc) from exc


@router.get("/evaluation")
def get_evaluation(db: Session = Depends(get_db)) -> dict:
    try:
        return gold_service.evaluate_gold(db)
    except GoldError as exc:
        raise _refus(exc) from exc
