import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.db.models.keyword import Keyword
from app.repositories.keyword_repo import KeywordRepository

router = APIRouter(
    prefix="/api/watchlist",
    tags=["watchlist"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class KeywordCreate(BaseModel):
    model_config = {"extra": "forbid"}

    term: str
    active: bool = True


class KeywordUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    term: str | None = None
    active: bool | None = None


class KeywordOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    term: str
    active: bool
    created_at: datetime


@router.get("", response_model=list[KeywordOut])
def list_keywords(db: Session = Depends(get_db)) -> list[Keyword]:
    return KeywordRepository(db).list()


@router.post(
    "",
    response_model=KeywordOut,
    status_code=201,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def create_keyword(payload: KeywordCreate, db: Session = Depends(get_db)) -> Keyword:
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Le terme ne peut pas être vide.")

    keyword = Keyword(
        id=uuid.uuid4(),
        term=term,
        active=payload.active,
        created_at=datetime.now(timezone.utc),
    )
    try:
        return KeywordRepository(db).create(keyword)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Ce terme est déjà surveillé: {term}"
        ) from exc


@router.patch(
    "/{keyword_id}",
    response_model=KeywordOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def update_keyword(
    keyword_id: uuid.UUID, payload: KeywordUpdate, db: Session = Depends(get_db)
) -> Keyword:
    repo = KeywordRepository(db)
    keyword = repo.get(keyword_id)
    if keyword is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    if payload.term is not None:
        term = payload.term.strip()
        if not term:
            raise HTTPException(
                status_code=400, detail="Le terme ne peut pas être vide."
            )
        keyword.term = term
    if payload.active is not None:
        keyword.active = payload.active

    try:
        return repo.update(keyword)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ce terme est déjà surveillé."
        ) from exc


@router.delete(
    "/{keyword_id}",
    status_code=204,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_keyword(keyword_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    KeywordRepository(db).delete(keyword_id)
