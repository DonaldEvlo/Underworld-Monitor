"""Temoin de l'isolation des tests d'integration (voir conftest.py).

⚠️ Un test d'isolation qui ne regarderait que depuis la session du test
passerait meme sans isolation. On verifie donc depuis une connexion
EXTERIEURE, ouverte directement sur le moteur : c'est le point de vue de
l'application reelle et des autres utilisateurs de la base.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.db.models.entity import Entity
from app.db.session import SessionLocal, engine


def _visible_de_l_exterieur(nom: str) -> bool:
    with engine.connect() as exterieur:
        return (
            exterieur.execute(
                text("select count(*) from entities where name = :n"), {"n": nom}
            ).scalar()
            > 0
        )


def test_un_commit_du_test_reste_invisible_hors_du_test():
    nom = f"__temoin_isolation_{uuid.uuid4().hex}"
    db = SessionLocal()
    db.add(Entity(id=uuid.uuid4(), name=nom, active=False))
    db.commit()  # un vrai commit, du point de vue du code teste

    # Visible depuis le test...
    assert db.query(Entity).filter(Entity.name == nom).count() == 1
    # ... mais pas depuis la base reelle.
    assert not _visible_de_l_exterieur(nom)
    db.close()


def test_la_fabrique_est_bien_rattachee_a_la_transaction(transaction_annulee):
    assert SessionLocal.kw["bind"] is transaction_annulee
