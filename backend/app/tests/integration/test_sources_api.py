"""Routes et taches de fond des sources, apres le decoupage du routeur
(2026-09-25) : ecritures, doublons d'URL, collecte groupee, test de
disponibilite, import GitHub.

Redis et le reseau sont simules. ⚠️ `TestClient` execute les BackgroundTasks
a la fin de la requete : chaque tache de fond lancee par une route est donc
REMPLACEE, sans quoi un test declencherait une vraie collecte via Tor.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.routers import sources as routeur
from app.db.models.source import Source
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.services import collect_batch_service as lots
from app.services import github_import_service as github
from app.services import source_test_job_service as tests_dispo
from app.tests.integration import factories as f


class _RedisSimule:
    def __init__(self):
        self.donnees: dict[str, str] = {}

    def get(self, cle):
        return self.donnees.get(cle)

    def set(self, cle, valeur, ex=None):
        self.donnees[cle] = valeur


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def redis(monkeypatch):
    faux = _RedisSimule()
    for module in (lots, github, tests_dispo):
        monkeypatch.setattr(module, "get_redis", lambda: faux)
    return faux


@pytest.fixture
def client(db, redis, monkeypatch):
    admin = User(id=uuid.uuid4(), username="t_admin", role="admin", active=True)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    # Aucune tache de fond reelle : elles collecteraient via Tor.
    lancees: list = []
    for nom in ("run_collect_all_job", "run_source_test_job", "run_github_import_job"):
        monkeypatch.setattr(routeur, nom, lambda *a, _n=nom: lancees.append((_n, a)))
    yield SimpleNamespace(http=TestClient(app), lancees=lancees)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _url() -> str:
    return f"http://{f.unique()}.onion"


class TestDoublonsDUrl:
    def test_creation_puis_doublon_refuse(self, client):
        url = _url()
        corps = {"name": "A", "type": "forum", "url": url}
        assert client.http.post("/api/sources", json=corps).status_code == 201
        # Meme adresse au schema pres : c'est un doublon (normalize_url).
        doublon = {**corps, "name": "B", "url": url.replace("http://", "https://")}
        reponse = client.http.post("/api/sources", json=doublon)
        assert reponse.status_code == 409
        assert "« A »" in reponse.json()["detail"]

    def test_modification_vers_une_adresse_prise_refusee(self, client, db):
        prise = f.source(db)
        autre = f.source(db)
        db.commit()
        reponse = client.http.patch(f"/api/sources/{autre.id}", json={"url": prise.url})
        assert reponse.status_code == 409

    def test_import_idempotent(self, client):
        url = _url()
        enveloppe = {
            "format": routeur.EXPORT_FORMAT,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": 1,
            "sources": [{"name": "Importee", "type": "forum", "url": url}],
        }
        premier = client.http.post("/api/sources/import", json=enveloppe).json()
        second = client.http.post("/api/sources/import", json=enveloppe).json()
        assert (premier["created"], premier["skipped"]) == (1, 0)
        assert (second["created"], second["skipped"]) == (0, 1)

    def test_format_d_import_inconnu_refuse(self, client):
        enveloppe = {
            "format": "autre.v9",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": 0,
            "sources": [],
        }
        assert (
            client.http.post("/api/sources/import", json=enveloppe).status_code == 400
        )


class TestCollecteGroupee:
    def test_la_route_lance_le_job_et_l_etat_est_consultable(self, client, redis):
        reponse = client.http.post("/api/sources/collect-all")
        assert reponse.status_code == 200
        batch_id = reponse.json()["batch_id"]
        assert client.lancees and client.lancees[0][0] == "run_collect_all_job"
        etat = client.http.get(f"/api/sources/collect-all/{batch_id}/status")
        assert etat.status_code == 200
        assert etat.json()["status"] == "running"

    def test_etat_inconnu_404(self, client):
        assert (
            client.http.get("/api/sources/collect-all/inconnu/status").status_code
            == 404
        )

    def test_le_job_collecte_chaque_source_et_termine(self, db, redis, monkeypatch):
        """Le job lui-meme, collecte remplacee par une doublure. Une source en
        echec ne fait pas echouer le lot."""
        ok, ko = f.source(db), f.source(db)
        db.commit()

        def collecte(_collecteur, _repo, source):
            if source.id == ok.id:
                return SimpleNamespace(
                    success=True,
                    text="contenu collecte",
                    saved_count=2,
                    duration_seconds=1,
                    collector_name="test",
                    error=None,
                )
            return SimpleNamespace(success=False, text=None, error="injoignable")

        monkeypatch.setattr(lots, "run_collect_source", collecte)
        monkeypatch.setattr(lots, "pick_collector", lambda s: object())
        # Un seul fil : la session de test ne doit pas etre partagee entre
        # fils concurrents ; l'estimation (qui lit la base) est neutralisee.
        monkeypatch.setattr(lots, "COLLECT_ALL_MAX_WORKERS", 1)
        monkeypatch.setattr(lots, "_estimer_temps_restant", lambda *_a: {})

        lots.run_collect_all_job("lot-test", [str(ok.id), str(ko.id)])

        etat = lots.load_job_status("lot-test")
        assert (etat.status, etat.total, etat.done) == ("done", 2, 2)
        par_source = {i.source_id: i for i in etat.items}
        assert (
            par_source[str(ok.id)].success and par_source[str(ok.id)].saved_count == 2
        )
        assert par_source[str(ko.id)].error == "injoignable"


class TestTestDeDisponibilite:
    def test_un_seul_test_a_la_fois(self, client):
        premier = client.http.post("/api/sources/test-jobs", json={}).json()
        second = client.http.post("/api/sources/test-jobs", json={}).json()
        assert premier["job_id"] == second["job_id"]
        assert len(client.lancees) == 1

    def test_source_inconnue_404(self, client):
        reponse = client.http.post(
            "/api/sources/test-jobs", json={"source_id": str(uuid.uuid4())}
        )
        assert reponse.status_code == 404

    def test_latest_rend_le_dernier_test(self, client):
        lance = client.http.post("/api/sources/test-jobs", json={"only_active": True})
        dernier = client.http.get("/api/sources/test-jobs/latest").json()
        assert dernier["job_id"] == lance.json()["job_id"]
        assert dernier["scope"] == "active"

    def test_le_job_passe_a_done(self, redis, monkeypatch):
        statut = tests_dispo.new_test_job("all")
        monkeypatch.setattr(tests_dispo, "load_sources", lambda *_a, **_k: [])
        monkeypatch.setattr(tests_dispo, "check_source_refs", lambda *_a, **_k: None)
        tests_dispo.run_source_test_job(statut.job_id, False, None)
        fini = tests_dispo.load_source_test_status(statut.job_id)
        assert (fini.status, fini.phase) == ("done", "done")
        assert fini.finished_at is not None

    def test_un_test_fige_est_declare_interrompu(self, redis):
        statut = tests_dispo.new_test_job("all")
        statut.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert tests_dispo.with_stale_check(statut).status == "error"
        # Et un test fige n'empeche pas d'en lancer un nouveau.
        tests_dispo._save_source_test_status(statut)
        assert tests_dispo.running_test() is None


class TestImportGitHub:
    def test_cree_les_joignables_inactives_et_ignore_les_doublons(
        self, db, redis, monkeypatch
    ):
        deja = f.source(db)
        db.commit()
        deja_url = deja.url
        # La tache ouvre SA session sur la meme connexion de test : on ferme la
        # notre avant, sinon leurs points de sauvegarde s'entremelent.
        db.close()
        nouvelle, morte = _url(), _url()
        import app.pipeline.collect.github_import as gi
        import app.pipeline.collect.onion_healthcheck as oh

        monkeypatch.setattr(gi, "fetch_all_lists", lambda: "liste")
        monkeypatch.setattr(
            gi,
            "find_new_candidates",
            lambda *_a: [("Nouvelle", nouvelle), ("Morte", morte), ("Deja", deja_url)],
        )
        monkeypatch.setattr(oh, "parse_onion_entries_from_text", lambda _t: [1, 2, 3])
        monkeypatch.setattr(
            github,
            "check_onion_entries",
            lambda candidats: [
                SimpleNamespace(
                    name=n, url=u, reachable=(n != "Morte"), http_status=200
                )
                for n, u in candidats
            ],
        )

        github.run_github_import_job("import-test")

        etat = github.load_github_import_status("import-test")
        assert etat.status == "done"
        assert [c.url for c in etat.created] == [nouvelle]
        assert etat.unreachable == 1
        verif = SessionLocal()
        try:
            creee = verif.query(Source).filter(Source.url == nouvelle).one()
            assert creee.active is False  # selection manuelle avant collecte
        finally:
            verif.close()
