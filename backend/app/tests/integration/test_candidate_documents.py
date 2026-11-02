"""Où une entité candidate est citée (2026-10-06). Transaction annulée."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.tests.integration import factories as f


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db):
    utilisateur = User(
        id=uuid.uuid4(), username="t_analyst", role="analyst", active=True
    )
    app.dependency_overrides[get_current_user] = lambda: utilisateur
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_les_documents_qui_citent_la_candidate(client, db):
    nom = f.unique("Nitrex ")
    src = f.source(db, name="SOURCE TEST (DLS)")
    for i in range(3):
        doc = f.document(db, src, title=f"Doc {i}")
        f.detection(db, doc, type_="organization", value_masked=nom)
    # Une autre candidate : jamais mélangée.
    f.detection(db, f.document(db, src), type_="organization", value_masked="Autre")
    db.commit()

    r = client.get(f"/api/entities/candidates/documents?name={nom}")
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["total"] == 3
    assert len(corps["items"]) == 3
    assert all(d["source_name"] == "SOURCE TEST (DLS)" for d in corps["items"])


def test_candidate_sans_citation(client):
    r = client.get("/api/entities/candidates/documents?name=Inexistante")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "offset": 0, "limit": 50, "items": []}


def test_la_route_n_est_pas_prise_pour_un_identifiant(client):
    """`candidates/documents` est déclarée avant `/{entity_id}/documents`."""
    assert client.get("/api/entities/candidates/documents?name=X").status_code == 200
