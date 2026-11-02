"""Sessions côté serveur et limitation des connexions (migration 0035,
2026-10-06). Transaction annulée (conftest) ; Redis remplacé par un double en
mémoire pour la limitation."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core import login_throttle
from app.core.security import create_access_token
from app.db.models.user_session import UserSession
from app.db.session import SessionLocal
from app.main import app
from app.services import session_service, user_service
from app.tests.integration import factories as f

MDP = "Mot-De-Passe-De-Test-2026!"


class _RedisMemoire:
    def __init__(self):
        self.v: dict[str, int] = {}
        self.exp: dict[str, float] = {}

    def get(self, k):
        return self.v.get(k)

    def incr(self, k):
        self.v[k] = self.v.get(k, 0) + 1
        return self.v[k]

    def expire(self, k, s):
        self.exp[k] = time.time() + s

    def ttl(self, k):
        return int(self.exp.get(k, time.time()) - time.time())

    def delete(self, k):
        self.v.pop(k, None)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(login_throttle, "get_redis", lambda: _RedisMemoire_partage)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
    _RedisMemoire_partage.v.clear()


_RedisMemoire_partage = _RedisMemoire()


@pytest.fixture
def compte(db):
    nom = f.unique("t_session_")
    return user_service.creer(db, username=nom, password=MDP, role="analyst")


def _connexion(client, nom, mdp=MDP):
    return client.post("/api/auth/login", json={"username": nom, "password": mdp})


def _entete(jetons):
    return {"Authorization": f"Bearer {jetons['access_token']}"}


class TestCycleDeVie:
    def test_connexion_puis_acces(self, client, compte):
        r = _connexion(client, compte.username)
        assert r.status_code == 200, r.text
        assert client.get("/api/auth/me", headers=_entete(r.json())).status_code == 200

    def test_la_deconnexion_est_reelle_cote_serveur(self, client, compte):
        """⚠️ Le cœur du chantier : après « Se déconnecter », NI le jeton
        d'accès NI le jeton de rafraîchissement ne servent plus."""
        jetons = _connexion(client, compte.username).json()
        assert (
            client.post("/api/auth/logout", headers=_entete(jetons)).status_code == 204
        )
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401
        r = client.post(
            "/api/auth/refresh", json={"refresh_token": jetons["refresh_token"]}
        )
        assert r.status_code == 401

    def test_deconnexion_pour_inactivite_tracee(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        client.post(
            "/api/auth/logout", headers=_entete(jetons), json={"reason": "idle"}
        )
        s = db.query(UserSession).filter_by(user_id=compte.id).one()
        assert s.revoked_reason == session_service.IDLE

    def test_dix_minutes_sans_requete_la_session_meurt(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        s = db.query(UserSession).filter_by(user_id=compte.id).one()
        s.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        db.commit()
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401
        db.refresh(s)
        assert s.revoked_reason == session_service.IDLE
        r = client.post(
            "/api/auth/refresh", json={"refresh_token": jetons["refresh_token"]}
        )
        assert r.status_code == 401

    def test_duree_maximale(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        s = db.query(UserSession).filter_by(user_id=compte.id).one()
        s.created_at = datetime.now(timezone.utc) - timedelta(hours=13)
        db.commit()
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401
        db.refresh(s)
        assert s.revoked_reason == session_service.EXPIRED

    def test_le_signal_d_activite_garde_la_session(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        s = db.query(UserSession).filter_by(user_id=compte.id).one()
        s.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=9)
        db.commit()
        assert (
            client.post("/api/auth/heartbeat", headers=_entete(jetons)).status_code
            == 204
        )
        db.refresh(s)
        assert datetime.now(timezone.utc) - s.last_seen_at < timedelta(seconds=5)

    def test_rafraichir_garde_la_meme_session(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        r = client.post(
            "/api/auth/refresh", json={"refresh_token": jetons["refresh_token"]}
        )
        assert r.status_code == 200
        assert client.get("/api/auth/me", headers=_entete(r.json())).status_code == 200
        assert db.query(UserSession).filter_by(user_id=compte.id).count() == 1

    def test_jeton_sans_session_refuse(self, client, compte):
        """Jeton émis avant la migration 0035 : non révocable, donc refusé."""
        ancien = create_access_token(compte.id)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ancien}"})
        assert r.status_code == 401

    def test_session_d_un_autre_compte_refusee(self, client, compte, db):
        autre = user_service.creer(db, username=f.unique("t_autre_"), password=MDP)
        jetons = _connexion(client, autre.username).json()
        sid = db.query(UserSession).filter_by(user_id=autre.id).one().id
        forge = create_access_token(compte.id, sid)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forge}"})
        assert r.status_code == 401
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 200


class TestRevocationParLeCompte:
    def test_changement_de_mot_de_passe(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        user_service.changer_mot_de_passe(db, compte, "Nouveau-Mot-De-Passe-2026!")
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401

    def test_changement_de_role(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        admin = user_service.creer(
            db, username=f.unique("t_adm_"), password=MDP, role="admin"
        )
        user_service.changer_role(db, compte, "viewer", demandeur=admin)
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401

    def test_desactivation(self, client, compte, db):
        jetons = _connexion(client, compte.username).json()
        admin = user_service.creer(
            db, username=f.unique("t_adm_"), password=MDP, role="admin"
        )
        user_service.changer_activation(db, compte, False, demandeur=admin)
        s = db.query(UserSession).filter_by(user_id=compte.id).one()
        assert s.revoked_reason == session_service.DEACTIVATED
        assert client.get("/api/auth/me", headers=_entete(jetons)).status_code == 401


class TestLimitationDesConnexions:
    def test_cinq_echecs_bloquent_le_compte(self, client, compte):
        for _ in range(login_throttle.MAX_PAR_COMPTE):
            assert _connexion(client, compte.username, "mauvais").status_code == 401
        r = _connexion(client, compte.username)  # même avec le BON mot de passe
        assert r.status_code == 429
        assert "Réessayez" in r.json()["detail"]

    def test_un_succes_remet_le_compteur_du_compte_a_zero(self, client, compte):
        for _ in range(login_throttle.MAX_PAR_COMPTE - 1):
            _connexion(client, compte.username, "mauvais")
        assert _connexion(client, compte.username).status_code == 200
        assert _connexion(client, compte.username, "mauvais").status_code == 401

    def test_compte_inconnu_meme_reponse(self, client):
        r = _connexion(client, f"inconnu-{uuid.uuid4().hex[:6]}", "x")
        assert r.status_code == 401 and r.json()["detail"] == "Identifiants invalides"

    def test_redis_indisponible_on_laisse_passer(self, client, compte, monkeypatch):
        def panne():
            raise ConnectionError("redis indisponible")

        monkeypatch.setattr(login_throttle, "get_redis", panne)
        assert _connexion(client, compte.username).status_code == 200
