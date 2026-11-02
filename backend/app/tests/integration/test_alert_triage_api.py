"""Note d'analyste, qualification de clôture et rappel (2026-10-02).

Constaté à l'usage : 20 alertes résolues, 0 note — l'interface n'avait aucun
champ de saisie. Et une alerte rouverte gardait son motif « faux positif »,
qui aurait continué de compter dans les statistiques de la Gouvernance.
"""

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
    analyste = User(id=uuid.uuid4(), username="t_analyste", role="analyst", active=True)
    app.dependency_overrides[get_current_user] = lambda: analyste
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def alerte(db):
    source = f.source(db)
    document = f.document(db, source)
    detection = f.detection(db, document)
    return f.alert(db, [detection], region=f"test-triage-{f.unique()}")


class TestNote:
    def test_la_note_est_enregistree_et_relue(self, client, alerte):
        r = client.patch(
            f"/api/alerts/{alerte.id}/triage",
            json={"analyst_note": "adresse .onion ouverte dans Tor, victime présente"},
        )
        assert r.status_code == 200
        assert (
            r.json()["analyst_note"]
            == "adresse .onion ouverte dans Tor, victime présente"
        )
        relue = client.get(f"/api/alerts/{alerte.id}").json()
        assert (
            relue["analyst_note"] == "adresse .onion ouverte dans Tor, victime présente"
        )

    def test_une_note_trop_longue_est_refusee(self, client, alerte):
        r = client.patch(
            f"/api/alerts/{alerte.id}/triage", json={"analyst_note": "x" * 4001}
        )
        assert r.status_code == 422


class TestCloture:
    def test_faux_positif_puis_cloture(self, client, alerte):
        client.patch(
            f"/api/alerts/{alerte.id}/triage",
            json={"resolution_reason": "false_positive"},
        )
        r = client.patch(f"/api/alerts/{alerte.id}/status", json={"status": "resolved"})
        assert r.status_code == 200
        corps = r.json()
        assert corps["status"] == "resolved"
        assert corps["resolution_reason"] == "false_positive"
        assert corps["resolved_at"] is not None

    def test_le_rappel_rouvre_et_retire_le_motif(self, client, alerte):
        client.patch(
            f"/api/alerts/{alerte.id}/triage",
            json={"resolution_reason": "false_positive"},
        )
        client.patch(f"/api/alerts/{alerte.id}/status", json={"status": "resolved"})
        r = client.post(f"/api/alerts/{alerte.id}/remind")
        assert r.status_code == 200
        corps = r.json()
        assert corps["status"] == "open"
        assert corps["resolution_reason"] is None
        assert corps["reminder_count"] == 1
