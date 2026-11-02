"""Gestion des comptes -- reserve a l'administrateur.

⚠️ AUCUN SCHEMA DE SORTIE NE PORTE `password_hash`. C'est la raison d'etre de
`UserOut` : renvoyer le modele tel quel exposerait le hachage a l'interface,
donc au journal du navigateur et a toute capture d'ecran. Verrouille par test.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import exige_role, get_current_user, get_db
from app.core.roles import PEUT_ADMINISTRER, Role
from app.db.models.user import User
from app.pipeline.enrich.hibp import HibpLookupError, check_password
from app.repositories.user_repo import UserRepository
from app.services import user_service

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)


class UserOut(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    username: str
    role: str
    active: bool
    created_at: object

    @classmethod
    def from_model(cls, u: User) -> "UserOut":
        # ⚠️ Champ par champ, JAMAIS `model_validate(u)` : une recopie
        # automatique embarquerait `password_hash` au premier ajout de champ.
        return cls(
            id=u.id,
            username=u.username,
            role=u.role,
            active=u.active,
            created_at=u.created_at,
        )


class CreateUserIn(BaseModel):
    model_config = {"extra": "forbid"}

    username: str
    password: str
    role: str = Role.ANALYST.value


class UpdateUserIn(BaseModel):
    model_config = {"extra": "forbid"}

    role: str | None = None
    active: bool | None = None
    password: str | None = None


class PasswordAdviceOut(BaseModel):
    """Avis consultatif sur un mot de passe, AVANT de le poser.

    ⚠️ Consultatif et non bloquant : HIBP peut etre injoignable, et un
    administrateur ne doit pas se retrouver incapable de creer un compte parce
    qu'une API tierce est en panne. `unavailable` distingue « non compromis »
    de « pas pu verifier » -- une absence de mesure n'est pas un resultat."""

    model_config = {"extra": "forbid"}

    breached: bool
    breach_count: int
    unavailable: bool


class PasswordCandidateIn(BaseModel):
    model_config = {"extra": "forbid"}

    password: str


def _cible(db: Session, user_id: uuid.UUID) -> User:
    utilisateur = UserRepository(db).get(user_id)
    if utilisateur is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return utilisateur


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.from_model(u) for u in user_service.lister(db)]


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: CreateUserIn, db: Session = Depends(get_db)) -> UserOut:
    try:
        return UserOut.from_model(
            user_service.creer(
                db,
                username=payload.username,
                password=payload.password,
                role=payload.role,
            )
        )
    except user_service.UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserIn,
    db: Session = Depends(get_db),
    demandeur: User = Depends(get_current_user),
) -> UserOut:
    utilisateur = _cible(db, user_id)
    try:
        if payload.role is not None:
            utilisateur = user_service.changer_role(
                db, utilisateur, payload.role, demandeur=demandeur
            )
        if payload.active is not None:
            utilisateur = user_service.changer_activation(
                db, utilisateur, payload.active, demandeur=demandeur
            )
        if payload.password is not None:
            utilisateur = user_service.changer_mot_de_passe(
                db, utilisateur, payload.password
            )
    except user_service.UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserOut.from_model(utilisateur)


@router.delete("/{user_id}", status_code=204, response_model=None)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    demandeur: User = Depends(get_current_user),
) -> None:
    try:
        user_service.supprimer(db, _cible(db, user_id), demandeur=demandeur)
    except user_service.UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/password-advice", response_model=PasswordAdviceOut)
def password_advice(payload: PasswordCandidateIn) -> PasswordAdviceOut:
    """Ce mot de passe figure-t-il dans des fuites connues ?

    ⚠️ **PREMIER USAGE REEL DU MODULE HIBP**, documente jusqu'ici comme
    « correct mais sans matiere » : le pipeline ne lui fournissait rien de
    rattachable. Un mot de passe qu'un administrateur s'apprete a poser, lui,
    est exactement ce qu'il sait juger.

    ⚠️ **k-anonymity** : seuls les 5 premiers caracteres du SHA-1 sortent,
    la comparaison se fait en local, et le hachage n'est JAMAIS persiste
    (voir enrich/hibp.py). Pwned **Passwords** uniquement -- jamais Pwned
    Accounts, qui exigerait d'envoyer une adresse en clair a un tiers
    (regle 2).

    ⚠️ Consultatif : une panne HIBP ne doit pas empecher de creer un compte.
    """
    try:
        resultat = check_password(payload.password)
    except (HibpLookupError, Exception):  # noqa: BLE001 - enrichissement
        return PasswordAdviceOut(breached=False, breach_count=0, unavailable=True)
    return PasswordAdviceOut(
        breached=resultat.is_breached,
        breach_count=resultat.breach_count,
        unavailable=False,
    )
