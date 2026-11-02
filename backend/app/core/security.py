import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def _create_token(
    subject: uuid.UUID,
    token_type: TokenType,
    expires_delta: timedelta,
    session_id: uuid.UUID | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    # Identifiant de la session côté serveur (migration 0035) : sans lui le
    # jeton ne peut pas être révoqué, et `get_current_user` le refuse.
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID | None = None) -> str:
    return _create_token(
        user_id,
        TokenType.ACCESS,
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        session_id,
    )


def create_refresh_token(
    user_id: uuid.UUID, session_id: uuid.UUID | None = None
) -> str:
    return _create_token(
        user_id,
        TokenType.REFRESH,
        timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        session_id,
    )


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    # `None` pour un jeton émis avant la migration 0035 : refusé par l'API.
    session_id: uuid.UUID | None


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    """Décode et valide un JWT : signature, expiration (vérifiées par pyjwt), et
    le champ `type` — un refresh token ne doit jamais être accepté là où un
    access token est attendu, et inversement."""
    return decode_claims(token, expected_type).user_id


def decode_claims(token: str, expected_type: TokenType) -> TokenClaims:
    """Comme `decode_token`, avec l'identifiant de session."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(
            f"Type de token inattendu (attendu: {expected_type.value})"
        )

    sub = payload.get("sub")
    if not sub:
        raise InvalidTokenError("Token sans sujet")

    try:
        user_id = uuid.UUID(sub)
        sid = payload.get("sid")
        session_id = uuid.UUID(sid) if sid else None
    except ValueError as exc:
        raise InvalidTokenError("Sujet de token invalide") from exc
    return TokenClaims(user_id, session_id)
