"""Script de creation de compte : le role demande est bien enregistre.

Sans `--role`, une installation neuve n'avait que des comptes `analyst` et
personne ne pouvait administrer la plateforme."""

from __future__ import annotations

import uuid

import pytest

from app.db.session import SessionLocal
from app.repositories.user_repo import UserRepository
from app.scripts import create_user

MDP = "MotDePasseAssezLong2026"


@pytest.fixture
def saisie(monkeypatch):
    monkeypatch.setattr(create_user.getpass, "getpass", lambda _invite: MDP)


def _role(username: str) -> str | None:
    with SessionLocal() as db:
        u = UserRepository(db).get_by_username(username)
        return u.role if u is not None else None


def test_le_role_admin_est_enregistre(saisie):
    nom = f"t_{uuid.uuid4().hex[:8]}_admin"
    assert create_user.main([nom, "--role", "admin"]) == 0
    assert _role(nom) == "admin"


def test_sans_role_le_compte_est_analyste(saisie):
    nom = f"t_{uuid.uuid4().hex[:8]}_defaut"
    assert create_user.main([nom]) == 0
    assert _role(nom) == "analyst"


def test_un_role_inconnu_est_refuse(saisie):
    with pytest.raises(SystemExit):
        create_user.main([f"t_{uuid.uuid4().hex[:8]}_x", "--role", "root"])
