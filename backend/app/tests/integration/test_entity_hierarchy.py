"""Groupes et filiales, pays et secteur déclarés, corrections d'analyste,
périmètre vu par le RSSI (migration 0033, 2026-10-05).

Tout tourne dans une transaction annulée (conftest.py) : aucune organisation
ni alerte réelle n'est touchée.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.entity import Entity
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.services.alert_service import generate_alerts, refresh_alert_severities
from app.services.victim_intel_service import apply_effective_facts
from app.tests.integration import factories as f


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _client(db, role: str) -> TestClient:
    utilisateur = User(id=uuid.uuid4(), username=f"t_{role}", role=role, active=True)
    app.dependency_overrides[get_current_user] = lambda: utilisateur
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture
def admin(db):
    yield _client(db, "admin")
    app.dependency_overrides.clear()


@pytest.fixture
def analyste(db):
    yield _client(db, "analyst")
    app.dependency_overrides.clear()


@pytest.fixture
def rssi(db):
    yield _client(db, "viewer")
    app.dependency_overrides.clear()


def _groupe_et_filiale(db):
    domaine_groupe = f"{f.unique('groupe')}.com"
    domaine_filiale = f"{f.unique('filiale')}.ci"
    groupe = f.entity(db, domain=domaine_groupe)
    filiale = f.entity(db, domain=domaine_filiale)
    filiale.parent_id = groupe.id
    db.commit()
    return groupe, filiale, domaine_groupe, domaine_filiale


class TestDeclaration:
    def test_creer_une_filiale_avec_pays_et_secteur(self, admin, db):
        groupe = admin.post("/api/entities", json={"name": f.unique("Groupe ")}).json()
        r = admin.post(
            "/api/entities",
            json={
                "name": f.unique("Filiale "),
                "parent_id": groupe["id"],
                "country": "ci",
                "sector": "Financial Services",
            },
        )
        assert r.status_code == 201, r.text
        corps = r.json()
        assert corps["parent_id"] == groupe["id"]
        assert corps["country"] == "CI"  # normalisé
        assert corps["sector"] == "Financial Services"

    def test_un_seul_niveau_de_groupe(self, admin, db):
        groupe, filiale, *_ = _groupe_et_filiale(db)
        r = admin.post(
            "/api/entities",
            json={"name": f.unique("Petite-fille "), "parent_id": str(filiale.id)},
        )
        assert r.status_code == 400
        r = admin.patch(
            f"/api/entities/{groupe.id}", json={"parent_id": str(filiale.id)}
        )
        assert r.status_code == 400

    def test_pas_son_propre_groupe(self, admin, db):
        groupe, *_ = _groupe_et_filiale(db)
        r = admin.patch(
            f"/api/entities/{groupe.id}", json={"parent_id": str(groupe.id)}
        )
        assert r.status_code == 400

    def test_pays_et_secteur_invalides_refuses(self, admin):
        assert (
            admin.post(
                "/api/entities", json={"name": f.unique("X "), "country": "SEN"}
            ).status_code
            == 400
        )
        assert (
            admin.post(
                "/api/entities", json={"name": f.unique("X "), "sector": "Banque"}
            ).status_code
            == 400
        )

    def test_null_explicite_retire_le_groupe(self, admin, db):
        _, filiale, *_ = _groupe_et_filiale(db)
        r = admin.patch(f"/api/entities/{filiale.id}", json={"parent_id": None})
        assert r.status_code == 200
        assert r.json()["parent_id"] is None

    def test_l_analyste_ne_declare_pas(self, analyste):
        assert analyste.post("/api/entities", json={"name": "x"}).status_code == 403

    def test_vocabulaire_des_secteurs(self, analyste):
        secteurs = analyste.get("/api/entities/sectors").json()
        critiques = {s["value"] for s in secteurs if s["critical"]}
        assert "Healthcare" in critiques
        assert "Manufacturing" not in critiques


class TestRattachement:
    def test_seule_la_filiale_est_alertee(self, db):
        """D2 : un domaine déclaré par le groupe ET la filiale alerte la filiale."""
        groupe, filiale, domaine_groupe, _ = _groupe_et_filiale(db)
        f.entity(db, domain="x.invalid")  # bruit
        from app.db.models.entity import EntitySelector

        db.add(
            EntitySelector(
                id=uuid.uuid4(),
                entity_id=filiale.id,
                type="domain",
                value=domaine_groupe,
            )
        )
        db.commit()
        doc = f.document(db, f.source(db))
        f.detection(db, doc, value_masked=domaine_groupe)
        db.commit()
        alertes = generate_alerts(db, entity_ids=[groupe.id, filiale.id], window_days=0)
        assert {a.entity_id for a in alertes} == {filiale.id}


class TestValeursEffectives:
    def _alerte(self, db, entite):
        doc = f.document(db, f.source(db))
        det = f.detection(db, doc)
        a = f.alert(db, [det], ent=entite)
        a.computed_country, a.computed_sector = "KE", "Manufacturing"
        a.victim_country, a.victim_sector = "KE", "Manufacturing"
        db.commit()
        return a

    def test_la_declaration_de_l_organisation_prime_sur_le_tiers(self, db):
        entite = f.entity(db, domain=f"{f.unique('d')}.com")
        entite.country, entite.sector = "EG", "Transportation"
        a = self._alerte(db, entite)
        apply_effective_facts(db, alert_ids=[a.id])
        db.refresh(a)
        assert (a.victim_country, a.victim_sector) == ("EG", "Transportation")
        assert (a.computed_country, a.computed_sector) == ("KE", "Manufacturing")

    def test_la_correction_de_l_analyste_prime_sur_tout(self, db):
        entite = f.entity(db, domain=f"{f.unique('d')}.com")
        entite.country = "EG"
        a = self._alerte(db, entite)
        a.country_override = "MA"
        db.commit()
        apply_effective_facts(db, alert_ids=[a.id])
        db.refresh(a)
        assert a.victim_country == "MA"


class TestCorrection:
    def _alerte(self, db):
        doc = f.document(db, f.source(db))
        det = f.detection(db, doc)
        entite = f.entity(db, domain=f"{f.unique('d')}.com")
        a = f.alert(db, [det], ent=entite, summary="ancien résumé")
        a.computed_severity = "medium"
        a.computed_country = "KE"
        a.victim_country = "KE"
        db.commit()
        return a

    def test_correction_avec_motif(self, analyste, db):
        a = self._alerte(db)
        r = analyste.put(
            f"/api/alerts/{a.id}/correction",
            json={
                "country": "eg",
                "severity": "high",
                "reason": "texte du gang : société égyptienne",
            },
        )
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["victim_country"] == "EG"
        assert corps["country_origin"] == "analyst"
        assert corps["computed_country"] == "KE"
        assert corps["severity"] == "high"
        assert corps["severity_origin"] == "analyst"
        assert corps["override_by"] == "t_analyst"
        assert corps["summary"] is None  # le résumé décrivait l'ancienne valeur

    def test_la_passe_horaire_ne_reecrit_pas_la_correction(self, analyste, db):
        a = self._alerte(db)
        analyste.put(
            f"/api/alerts/{a.id}/correction",
            json={"severity": "critical", "reason": "décision d'analyste"},
        )
        refresh_alert_severities(db, apply=True, alert_ids=[a.id])
        db.refresh(a)
        assert a.severity == "critical"
        assert a.computed_severity == "medium"

    def test_motif_obligatoire(self, analyste, db):
        a = self._alerte(db)
        r = analyste.put(
            f"/api/alerts/{a.id}/correction", json={"country": "EG", "reason": ""}
        )
        assert r.status_code == 422

    def test_annuler_la_correction(self, analyste, db):
        a = self._alerte(db)
        analyste.put(
            f"/api/alerts/{a.id}/correction",
            json={"country": "EG", "reason": "pays erroné"},
        )
        r = analyste.delete(f"/api/alerts/{a.id}/correction")
        assert r.status_code == 200
        assert r.json()["victim_country"] == "KE"
        assert r.json()["override_reason"] is None


class TestFiltreDeGroupe:
    def test_le_groupe_voit_ses_filiales(self, analyste, db):
        groupe, filiale, *_ = _groupe_et_filiale(db)
        autre = f.entity(db, domain=f"{f.unique('d')}.com")
        doc = f.document(db, f.source(db))
        ids = {f.alert(db, [f.detection(db, doc)], ent=e).id for e in (groupe, filiale)}
        f.alert(db, [f.detection(db, doc)], ent=autre)
        corps = analyste.get(f"/api/alerts?group_id={groupe.id}&limit=50").json()
        assert {a["id"] for a in corps["items"]} == {str(i) for i in ids}
        assert corps["total"] == 2
        filiale_ligne = next(
            a for a in corps["items"] if a["entity_id"] == str(filiale.id)
        )
        assert filiale_ligne["group_name"] == groupe.name


class TestPerimetreRSSI:
    def test_le_rssi_voit_son_perimetre_par_nom(self, rssi, db):
        groupe, filiale, *_ = _groupe_et_filiale(db)
        doc = f.document(db, f.source(db))
        f.alert(db, [f.detection(db, doc)], ent=filiale, severity="high")
        r = rssi.get("/api/perimeter")
        assert r.status_code == 200
        ligne = next(g for g in r.json()["groups"] if g["id"] == str(groupe.id))
        assert [s["name"] for s in ligne["subsidiaries"]] == [filiale.name]
        assert ligne["group_open_by_severity"]["high"] == 1

    def test_synthese_sans_preuve(self, rssi, db):
        _, filiale, *_ = _groupe_et_filiale(db)
        doc = f.document(db, f.source(db))
        f.alert(db, [f.detection(db, doc)], ent=filiale)
        corps = rssi.get(f"/api/perimeter/{filiale.id}/alerts").json()
        cles = set(corps["alerts"][0])
        # ⚠️ La frontière : ni détection, ni valeur, ni document, ni URL.
        assert cles == {
            "id",
            "alert_date",
            "severity",
            "status",
            "credibility_level",
            "summary",
            "resolution_reason",
            "acknowledged_at",
            "resolved_at",
            "organization",
        }

    def test_les_alertes_regionales_sont_exclues(self, rssi, db):
        groupe, *_ = _groupe_et_filiale(db)
        doc = f.document(db, f.source(db))
        f.alert(db, [f.detection(db, doc)], region=f.unique("test-perimetre-"))
        corps = rssi.get(f"/api/perimeter/{groupe.id}/alerts").json()
        assert corps["alerts"] == []

    def test_le_rssi_n_accede_toujours_pas_aux_alertes_detaillees(self, rssi):
        assert rssi.get("/api/alerts").status_code == 403

    def test_organisation_inconnue(self, rssi):
        assert rssi.get(f"/api/perimeter/{uuid.uuid4()}/alerts").status_code == 404


def test_une_entite_supprimee_libere_ses_filiales(db):
    """`ON DELETE SET NULL` : supprimer un groupe ne supprime pas ses filiales."""
    groupe, filiale, *_ = _groupe_et_filiale(db)
    for s in list(groupe.selectors):
        db.delete(s)
    db.delete(groupe)
    db.commit()
    db.refresh(filiale)
    assert db.get(Entity, filiale.id).parent_id is None
