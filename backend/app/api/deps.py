from collections.abc import Iterable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.roles import Role, role_de
from app.core.security import InvalidTokenError, TokenType, decode_claims
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.db.session import get_db
from app.repositories.user_repo import UserRepository
from app.services import session_service

_bearer_scheme = HTTPBearer(auto_error=False)


def _authentifier(
    credentials: HTTPAuthorizationCredentials | None, db: Session
) -> tuple[User, UserSession]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentification requise")
    erreur = HTTPException(status_code=401, detail="Token invalide ou expiré")
    try:
        claims = decode_claims(credentials.credentials, TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise erreur from exc

    user = UserRepository(db).get(claims.user_id)
    if user is None or not user.active:
        raise erreur
    # ⚠️ Un jeton valide ne suffit pas : sa SESSION doit vivre encore. C'est
    # ce qui rend effectives la déconnexion, l'expiration par inactivité et la
    # révocation au changement de mot de passe (migration 0035).
    try:
        session = session_service.validate(db, claims.session_id, user.id)
    except session_service.SessionInvalid as exc:
        raise erreur from exc
    return user, session


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    return _authentifier(credentials, db)[0]


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> UserSession:
    return _authentifier(credentials, db)[1]


def exige_role(roles_autorises: Iterable[Role]):
    """Garde d'acces : refuse 403 si le role de l'appelant n'est pas autorise.

    ⚠️ **403, PAS 404.** Cacher l'existence d'une route a un utilisateur DEJA
    authentifie de l'organisation n'apporte rien et rend le refus
    indiagnosticable : l'analyste conclurait a une panne. On dit « vous n'avez
    pas ce droit », pas « cela n'existe pas ».

    ⚠️ **Posee sur le ROUTER, pas sur chaque fonction.** Une garde oubliee sur
    un seul endpoint est un trou qu'aucun test de la route voisine ne revele --
    c'est le meme raisonnement que la liste blanche d'actions planifiables,
    ou le filtrage est refait a la lecture plutot que confie a l'appelant.

    Le message nomme le role manquant : un refus sans motif se lit comme un
    bug."""
    autorises = frozenset(roles_autorises)

    def garde(current_user: User = Depends(get_current_user)) -> User:
        if role_de(current_user.role) not in autorises:
            attendus = ", ".join(sorted(r.value for r in autorises))
            raise HTTPException(
                status_code=403,
                detail=f"Acces refuse : role requis ({attendus})",
            )
        return current_user

    return garde


__all__ = ["get_db", "get_current_user", "exige_role"]
