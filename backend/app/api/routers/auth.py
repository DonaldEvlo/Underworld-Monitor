from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_session, get_current_user, get_db
from app.contracts.auth import LoginRequest, RefreshRequest, TokenPair, UserContract
from app.core import login_throttle
from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_claims,
    hash_password,
    verify_password,
)
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.repositories.user_repo import UserRepository
from app.services import session_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ⚠️ Vérification factice quand l'identifiant n'existe pas : sans elle, la
# réponse était plus rapide pour un compte inconnu (argon2 non exécuté), ce qui
# révélait par la mesure du temps quels comptes existent.
_EMPREINTE_FACTICE = hash_password("compte-inexistant-verification-factice")


def _adresse(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenPair:
    adresse = _adresse(request)
    attente = login_throttle.blocked_for(payload.username, adresse)
    if attente:
        raise HTTPException(
            status_code=429,
            detail=(
                "Trop de tentatives de connexion. Réessayez dans "
                f"{max(1, round(attente / 60))} minute(s)."
            ),
        )

    user = UserRepository(db).get_by_username(payload.username)
    empreinte = user.password_hash if user is not None else _EMPREINTE_FACTICE
    mot_de_passe_ok = verify_password(payload.password, empreinte)
    # Message volontairement identique pour identifiant inconnu et mot de passe
    # invalide -- ne pas révéler si un nom d'utilisateur existe en base.
    if user is None or not user.active or not mot_de_passe_ok:
        login_throttle.record_failure(payload.username, adresse)
        raise HTTPException(status_code=401, detail="Identifiants invalides")

    login_throttle.record_success(payload.username)
    session = session_service.open_session(db, user.id)
    return TokenPair(
        access_token=create_access_token(user.id, session.id),
        refresh_token=create_refresh_token(user.id, session.id),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    erreur = HTTPException(status_code=401, detail="Refresh token invalide ou expiré")
    try:
        claims = decode_claims(payload.refresh_token, TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise erreur from exc

    user = UserRepository(db).get(claims.user_id)
    if user is None or not user.active:
        raise erreur
    # ⚠️ Le refresh token seul ne suffit plus : sa SESSION doit vivre encore
    # (non révoquée, active depuis moins de 10 min, ouverte depuis moins de
    # 12 h). C'est ce qui rend la déconnexion réelle côté serveur.
    try:
        session = session_service.validate(db, claims.session_id, user.id)
    except session_service.SessionInvalid as exc:
        raise erreur from exc

    return TokenPair(
        access_token=create_access_token(user.id, session.id),
        refresh_token=create_refresh_token(user.id, session.id),
    )


class LogoutRequest(BaseModel):
    model_config = {"extra": "forbid"}

    # "idle" quand l'interface déconnecte pour inactivité : le motif est tracé.
    reason: Literal["logout", "idle"] = "logout"


@router.post("/logout", status_code=204, response_model=None)
def logout(
    payload: LogoutRequest | None = None,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    """Révoque la session courante : ses jetons (accès ET rafraîchissement)
    deviennent inutilisables immédiatement, sur tous les onglets."""
    motif = payload.reason if payload else "logout"
    session_service.revoke(
        db, session, session_service.IDLE if motif == "idle" else session_service.LOGOUT
    )


@router.post("/heartbeat", status_code=204, response_model=None)
def heartbeat(_: User = Depends(get_current_user)) -> None:
    """Signal d'activité de l'utilisateur. L'authentification suffit : elle
    touche la session (`get_current_user`). Envoyé par le navigateur quand
    l'utilisateur agit sans déclencher d'appel (lecture d'un long document),
    sans quoi la session expirerait côté serveur alors qu'il est présent."""


@router.get("/me", response_model=UserContract)
def me(current_user: User = Depends(get_current_user)) -> UserContract:
    return UserContract.model_validate(current_user, from_attributes=True)
