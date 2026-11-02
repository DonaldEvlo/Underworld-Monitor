"""Gestion des comptes -- creation, role, activation, mot de passe.

⚠️ CE SERVICE PEUT VERROUILLER L'OUTIL HORS DE PORTEE DE SON PROPRIETAIRE.
C'est sa particularite : retirer le dernier role `admin`, ou desactiver le
dernier administrateur, rend la configuration DEFINITIVEMENT inaccessible par
l'interface -- il faudrait repasser par la base. Les garde-fous ci-dessous ne
sont donc pas du confort, ils sont la fonction.

⚠️ AUCUN MOT DE PASSE N'EST JAMAIS RENDU NI JOURNALISE. On ne stocke que le
hachage argon2 (`core/security.hash_password`). Un contrat de sortie qui
porterait `password_hash` fuiterait un secret vers l'interface : les schemas
de `api/routers/users.py` l'excluent, et un test le verrouille.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.roles import Role, role_de
from app.core.security import hash_password
from app.db.models.user import User
from app.services import session_service

logger = logging.getLogger(__name__)

# Plancher volontairement modeste : ce n'est pas une politique de mot de passe
# d'entreprise, c'est un filet contre « admin »/« 1234 ». La vraie mesure de
# qualite est le controle HIBP ci-dessous, qui repose sur des fuites reelles
# plutot que sur des regles de composition -- lesquelles produisent surtout
# des mots de passe previsibles.
LONGUEUR_MINIMALE = 12


class UserServiceError(Exception):
    """Refus metier : le routeur le traduit en 400."""


def _admins_actifs(db: Session, *, sauf: uuid.UUID | None = None) -> int:
    q = db.query(User).filter(User.active.is_(True), User.role == Role.ADMIN.value)
    if sauf is not None:
        q = q.filter(User.id != sauf)
    return q.count()


def lister(db: Session) -> list[User]:
    return db.query(User).order_by(User.username).all()


def creer(
    db: Session, *, username: str, password: str, role: str = Role.ANALYST.value
) -> User:
    nom = (username or "").strip()
    if len(nom) < 3:
        raise UserServiceError("L'identifiant doit faire au moins 3 caracteres")
    if db.query(User).filter(User.username == nom).first() is not None:
        raise UserServiceError("Cet identifiant existe deja")
    _valider_mot_de_passe(password)

    utilisateur = User(
        id=uuid.uuid4(),
        username=nom,
        password_hash=hash_password(password),
        active=True,
        # ⚠️ Une valeur de role inconnue retombe sur `viewer`, jamais sur
        # `admin` (voir core/roles.role_de). Creer un compte ne doit pas
        # pouvoir donner l'administration par une faute de frappe.
        role=role_de(role).value,
    )
    db.add(utilisateur)
    db.commit()
    db.refresh(utilisateur)
    return utilisateur


def changer_role(
    db: Session, utilisateur: User, nouveau_role: str, *, demandeur: User
) -> User:
    cible = role_de(nouveau_role)
    ancien = role_de(utilisateur.role)
    if cible is ancien:
        return utilisateur
    # ⚠️ GARDE ANTI-VERROUILLAGE : retirer le DERNIER administrateur rendrait
    # la configuration inaccessible par l'interface pour toujours.
    if ancien is Role.ADMIN and _admins_actifs(db, sauf=utilisateur.id) == 0:
        raise UserServiceError(
            "Impossible : ce compte est le dernier administrateur actif"
        )
    utilisateur.role = cible.value
    # Un rôle retiré prend effet tout de suite, pas à l'expiration du jeton.
    session_service.revoke_all_for_user(
        db, utilisateur.id, session_service.ROLE_CHANGED
    )
    db.commit()
    db.refresh(utilisateur)
    logger.info(
        "Role modifie: %s -> %s (par %s)",
        utilisateur.username,
        cible.value,
        demandeur.username,
    )
    return utilisateur


def changer_activation(
    db: Session, utilisateur: User, actif: bool, *, demandeur: User
) -> User:
    # ⚠️ ON NE SE DESACTIVE PAS SOI-MEME : le geste est irreversible depuis
    # l'interface (une session desactivee ne peut plus rien faire), et il est
    # presque toujours une erreur de manipulation.
    if not actif and utilisateur.id == demandeur.id:
        raise UserServiceError("Impossible de desactiver son propre compte")
    if (
        not actif
        and role_de(utilisateur.role) is Role.ADMIN
        and _admins_actifs(db, sauf=utilisateur.id) == 0
    ):
        raise UserServiceError(
            "Impossible : ce compte est le dernier administrateur actif"
        )
    utilisateur.active = actif
    if not actif:
        session_service.revoke_all_for_user(
            db, utilisateur.id, session_service.DEACTIVATED
        )
    db.commit()
    db.refresh(utilisateur)
    return utilisateur


def changer_mot_de_passe(db: Session, utilisateur: User, nouveau: str) -> User:
    _valider_mot_de_passe(nouveau)
    utilisateur.password_hash = hash_password(nouveau)
    # ⚠️ Changer un mot de passe (souvent parce qu'il a fuité) doit déconnecter
    # toutes les sessions ouvertes avec l'ancien.
    session_service.revoke_all_for_user(
        db, utilisateur.id, session_service.PASSWORD_CHANGED
    )
    db.commit()
    # ⚠️ Le mot de passe n'apparait NI dans le retour, NI dans le journal.
    logger.info("Mot de passe modifie pour %s", utilisateur.username)
    return utilisateur


def supprimer(db: Session, utilisateur: User, *, demandeur: User) -> None:
    if utilisateur.id == demandeur.id:
        raise UserServiceError("Impossible de supprimer son propre compte")
    if (
        role_de(utilisateur.role) is Role.ADMIN
        and _admins_actifs(db, sauf=utilisateur.id) == 0
    ):
        raise UserServiceError(
            "Impossible : ce compte est le dernier administrateur actif"
        )
    # ℹ️ Le journal des acces SURVIT a la suppression : `alert_accesses.user_id`
    # est en `ON DELETE SET NULL` et la ligne conserve `username` et `role`
    # d'alors (migration 0028). Supprimer un compte n'efface pas sa trace.
    db.delete(utilisateur)
    db.commit()


def _valider_mot_de_passe(password: str) -> None:
    if len(password or "") < LONGUEUR_MINIMALE:
        raise UserServiceError(
            f"Le mot de passe doit faire au moins {LONGUEUR_MINIMALE} caracteres"
        )
