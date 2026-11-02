"""Sessions côté serveur (migration 0035).

Une session meurt :
- à la déconnexion (manuelle, ou par inactivité dans le navigateur) ;
- après `SESSION_IDLE_TIMEOUT_MINUTES` sans requête authentifiée (onglet
  fermé, poste en veille — le navigateur ne peut alors rien signaler) ;
- au plus tard `SESSION_MAX_HOURS` après la connexion ;
- quand le mot de passe, le rôle ou l'activation du compte changent.

⚠️ Une session expirée est RÉVOQUÉE dès qu'on la constate (motif tracé),
jamais simplement refusée : sinon un jeton refusé à 10 min 01 redeviendrait
valide si l'horloge… ou la configuration changeait.

⚠️ Les collectes, l'alerting et toutes les tâches de fond ne dépendent
d'AUCUNE session : elles tournent dans les workers Celery (ou en tâche de fond
de l'API) avec leur propre accès à la base. Déconnecter un utilisateur
n'arrête rien.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.user_session import UserSession

logger = logging.getLogger(__name__)

# `last_seen_at` n'est réécrit qu'au-delà de cet écart : une écriture par
# requête serait inutilement coûteuse (l'interface interroge l'API souvent).
_TOUCH_EVERY = timedelta(seconds=30)

LOGOUT = "logout"
IDLE = "idle"
EXPIRED = "expired"
PASSWORD_CHANGED = "password_changed"
ROLE_CHANGED = "role_changed"
DEACTIVATED = "deactivated"


class SessionInvalid(Exception):
    """La session n'existe pas, est révoquée ou a expiré."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def expiry_reason(session: UserSession, now: datetime) -> str | None:
    """Pourquoi la session doit mourir maintenant, ou None si elle vit.
    Logique pure : testable sans base."""
    if now - session.last_seen_at > timedelta(
        minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES
    ):
        return IDLE
    if now - session.created_at > timedelta(hours=settings.SESSION_MAX_HOURS):
        return EXPIRED
    return None


def open_session(db: Session, user_id: uuid.UUID) -> UserSession:
    maintenant = _now()
    session = UserSession(
        id=uuid.uuid4(), user_id=user_id, created_at=maintenant, last_seen_at=maintenant
    )
    db.add(session)
    db.commit()
    return session


def revoke(db: Session, session: UserSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = _now()
        session.revoked_reason = reason
        db.commit()


def validate(
    db: Session, session_id: uuid.UUID | None, user_id: uuid.UUID
) -> UserSession:
    """Session vivante appartenant à `user_id`, touchée ; sinon SessionInvalid."""
    if session_id is None:
        # Jeton émis avant la migration 0035 : non révocable, donc refusé.
        raise SessionInvalid("jeton sans session")
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user_id or session.revoked_at is not None:
        raise SessionInvalid("session révoquée ou inconnue")
    maintenant = _now()
    motif = expiry_reason(session, maintenant)
    if motif is not None:
        revoke(db, session, motif)
        raise SessionInvalid(f"session expirée ({motif})")
    if maintenant - session.last_seen_at >= _TOUCH_EVERY:
        session.last_seen_at = maintenant
        db.commit()
    return session


def revoke_all_for_user(db: Session, user_id: uuid.UUID, reason: str) -> int:
    """Révoque toutes les sessions vivantes d'un utilisateur (changement de
    mot de passe, de rôle, désactivation). Ne valide pas la transaction : le
    changement qui la motive et la révocation partent ensemble."""
    resultat = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    n = int(getattr(resultat, "rowcount", 0) or 0)
    if n:
        logger.info("%d session(s) révoquée(s) (%s)", n, reason)
    return n
