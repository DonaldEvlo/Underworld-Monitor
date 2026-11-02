"""Changements d'adresse : les deux passes, la preuve et la bascule
(2026-10-05). Réseau entièrement simulé ; transaction annulée (conftest)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.source_address_change import SourceAddressChange
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.pipeline.collect import host_aliases
from app.pipeline.collect.address_change import APPLIED, PENDING, REJECTED
from app.pipeline.collect.dls.scraper import DlsVictim, pick_parser
from app.services import source_address_service as service
from app.tests.integration import factories as f

ANCIEN = "krybit" + "a" * 50 + ".onion"
NOUVEAU = "b" * 56 + ".onion"  # sans le marqueur « krybit » : l'alias est requis
CONNUES = ["Acme Corp", "Exemplo Corporation", "Domaine Exemple", "Air Example"]


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()
    host_aliases.configure(None)


@pytest.fixture
def source_dls(db, monkeypatch):
    src = f.source(db, name="KRYBIT TEST (DLS)")
    src.url = f"http://{ANCIEN}"
    src.active = True
    for nom in CONNUES:
        f.document(db, src, title=nom)
    db.commit()
    # Seule cette source est examinée : la base réelle reste hors du test.
    monkeypatch.setattr(service, "_sources_actives", lambda _db: [src])
    return src


def _victimes(*noms: str) -> list[DlsVictim]:
    return [DlsVictim(name=n, site=None, description=None) for n in noms]


def _reseau(monkeypatch, pages: dict[str, str], victimes: dict[str, list[DlsVictim]]):
    """`fetch` et `parse_dls` simulés : clé = hôte de l'URL demandée."""

    def fetch(url: str) -> str:
        for hote, page in pages.items():
            if hote in url:
                return page
        raise ConnectionError(url)

    def parse(html: str, url: str):
        for hote, vs in victimes.items():
            if hote in url:
                return vs
        return []

    monkeypatch.setattr(service, "parse_dls", parse)
    return fetch


def _lignes(db, src):
    return db.query(SourceAddressChange).filter_by(source_id=src.id).all()


class TestDepuisLeSite:
    def test_demenagement_prouve_bascule_et_garde_le_parser(
        self, db, source_dls, monkeypatch
    ):
        fetch = _reseau(
            monkeypatch,
            {
                ANCIEN: f"<h1>Migration completed</h1> {NOUVEAU}",
                NOUVEAU: "<html>liste</html>",
            },
            {NOUVEAU: _victimes(*CONNUES, "Nouvelle victime")},
        )
        bilan = service.verifier_depuis_les_sites(db, fetch=fetch)
        db.refresh(source_dls)
        assert len(bilan["applied"]) == 1
        assert source_dls.url == f"http://{NOUVEAU}"
        (ligne,) = _lignes(db, source_dls)
        assert ligne.status == APPLIED and ligne.common_victims == 4
        assert ligne.old_url == f"http://{ANCIEN}"
        # ⚠️ Le point qui compte : le parser dédié suit la source.
        host_aliases.configure(service.alias_depuis_la_base)
        assert pick_parser(f"http://{NOUVEAU}") is not None

    def test_annonce_d_un_autre_site_quand_l_actuel_fonctionne(
        self, db, source_dls, monkeypatch
    ):
        """Cas LockBit 3 -> 5 : annonce dans le flux, l'ancien site publie toujours."""
        f.document(
            db,
            source_dls,
            title="new blog domain lockbit 5.0",
            content=f"http://{NOUVEAU}",
        )
        db.commit()
        fetch = _reseau(
            monkeypatch,
            {ANCIEN: "<html>liste</html>", NOUVEAU: "<html>autre liste</html>"},
            {ANCIEN: _victimes(*CONNUES), NOUVEAU: _victimes(*CONNUES[:3], "X", "Y")},
        )
        bilan = service.verifier_depuis_les_sites(db, fetch=fetch)
        db.refresh(source_dls)
        assert source_dls.url == f"http://{ANCIEN}"
        assert bilan["applied"] == []
        (ligne,) = _lignes(db, source_dls)
        assert ligne.status == PENDING and "fonctionne encore" in ligne.reason
        assert "new blog domain" in ligne.evidence

    def test_autres_victimes_reste_a_examiner(self, db, source_dls, monkeypatch):
        fetch = _reseau(
            monkeypatch,
            {ANCIEN: f"We have moved to {NOUVEAU}", NOUVEAU: "<html>liste</html>"},
            {NOUVEAU: _victimes("A", "B", "C", "D")},
        )
        service.verifier_depuis_les_sites(db, fetch=fetch)
        db.refresh(source_dls)
        assert source_dls.url == f"http://{ANCIEN}"
        assert _lignes(db, source_dls)[0].status == PENDING

    def test_une_candidate_rejetee_n_est_plus_reproposee(
        self, db, source_dls, monkeypatch
    ):
        fetch = _reseau(
            monkeypatch,
            {ANCIEN: f"We have moved to {NOUVEAU}", NOUVEAU: "<html>liste</html>"},
            {NOUVEAU: _victimes("A", "B", "C")},
        )
        service.verifier_depuis_les_sites(db, fetch=fetch)
        (ligne,) = _lignes(db, source_dls)
        service.rejeter(db, ligne.id, "t_admin")
        bilan = service.verifier_depuis_les_sites(db, fetch=fetch)
        assert bilan["candidates"] == 0
        db.refresh(ligne)
        assert ligne.status == REJECTED


class TestDepuisDeepDarkCTI:
    def _liste(self, statut_ancien: str) -> str:
        return (
            "|Name|Status|\n|---|---|\n"
            f"|[KRYBIT TEST](http://{ANCIEN})|{statut_ancien}|\n"
            f"|[KRYBIT TEST (mirror)](http://{NOUVEAU})|ONLINE|\n"
        )

    def test_notre_adresse_offline_bascule_sur_preuve(
        self, db, source_dls, monkeypatch
    ):
        from datetime import datetime, timezone

        source_dls.last_collected_at = datetime.now(timezone.utc)
        db.commit()
        fetch = _reseau(
            monkeypatch,
            {NOUVEAU: "<html>liste</html>"},  # l'ancienne ne répond plus
            {NOUVEAU: _victimes(*CONNUES)},
        )
        bilan = service.verifier_depuis_deepdarkcti(
            db, fetch=fetch, lire_listes=lambda: self._liste("OFFLINE")
        )
        db.refresh(source_dls)
        assert source_dls.url == f"http://{NOUVEAU}"
        assert bilan["applied"][0]["new_url"] == f"http://{NOUVEAU}"
        assert _lignes(db, source_dls)[0].origin == "deepdarkcti"

    def test_notre_adresse_online_et_collecte_a_jour_on_ne_touche_a_rien(
        self, db, source_dls, monkeypatch
    ):
        from datetime import datetime, timezone

        source_dls.last_collected_at = datetime.now(timezone.utc)
        db.commit()
        fetch = _reseau(monkeypatch, {}, {})
        bilan = service.verifier_depuis_deepdarkcti(
            db, fetch=fetch, lire_listes=lambda: self._liste("ONLINE")
        )
        assert bilan["candidates"] == 0 and _lignes(db, source_dls) == []

    def test_liste_illisible_est_une_erreur_pas_un_succes(self, db, source_dls):
        bilan = service.verifier_depuis_deepdarkcti(db, lire_listes=lambda: "")
        assert bilan["errors"] == 1


def _client(db, role: str) -> TestClient:
    utilisateur = User(id=uuid.uuid4(), username=f"t_{role}", role=role, active=True)
    app.dependency_overrides[get_current_user] = lambda: utilisateur
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class TestApi:
    def test_droits(self, db):
        try:
            assert _client(db, "viewer").get("/api/source-addresses").status_code == 403
            analyste = _client(db, "analyst")
            assert analyste.get("/api/source-addresses").status_code == 200
            assert (
                analyste.post(f"/api/source-addresses/{uuid.uuid4()}/apply").status_code
                == 403
            )
            assert (
                analyste.post("/api/source-addresses/run?origin=site").status_code
                == 403
            )
        finally:
            app.dependency_overrides.clear()

    def test_application_manuelle(self, db, source_dls, monkeypatch):
        fetch = _reseau(
            monkeypatch,
            {ANCIEN: f"We have moved to {NOUVEAU}", NOUVEAU: "<html>forum</html>"},
            {},
        )
        service.verifier_depuis_les_sites(db, fetch=fetch)
        (ligne,) = _lignes(db, source_dls)
        try:
            r = _client(db, "admin").post(f"/api/source-addresses/{ligne.id}/apply")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == APPLIED and r.json()["decided_by"] == "t_admin"
        finally:
            app.dependency_overrides.clear()
        db.refresh(source_dls)
        assert source_dls.url == f"http://{NOUVEAU}"
