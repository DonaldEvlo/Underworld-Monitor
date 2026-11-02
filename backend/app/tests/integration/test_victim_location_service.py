"""Victimes sans domaine localisable : pays declare -> alerte regionale.

Reseau entierement SIMULE (ransomware.live). Transaction annulee a la fin de
chaque test (conftest.py) : rien n'est ecrit dans la base reelle."""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.services import victim_location_service as svc
from app.services.alert_service import generate_alerts
from app.tests.integration import factories as f

NDF = {
    "victim": "Exemple Defence Force",
    "domain": "www.defense-exemple.gov.na",
    "country": "NA",
    "group": "ransomhouse",
}


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def reseau(monkeypatch):
    """ransomware.live simule : victimes recentes + historiques par gang."""
    etat = {"recentes": [], "historiques": {}, "en_cache": set(), "appels": []}

    monkeypatch.setattr(svc, "_victimes_recentes", lambda: (etat["recentes"], False))

    def payload(gang):
        etat["appels"].append(gang)
        return etat["historiques"].get(gang, [])

    monkeypatch.setattr(svc, "payload_rwl", payload)
    monkeypatch.setattr(svc, "rwl_payload_cached", lambda g: g in etat["en_cache"])
    return etat


def _victime_ransomlook(db, titre, gang, *, detection_type="organization", valeur=None):
    src = f.source(db, name=f"{f.unique('RANSOMLOOK')} (agregateur)", type_="forum")
    doc = f.document(
        db, src, collector="ransomlook", title=titre, source_meta={"group_name": gang}
    )
    det = f.detection(db, doc, type_=detection_type, value_masked=valeur or titre)
    return doc, det


class TestLocalisation:
    def test_une_victime_sans_domaine_recoit_son_pays_declare(self, db, reseau):
        reseau["historiques"]["ransomhouse"] = [NDF]
        # « En cache » : lu hors budget d'appels. Sinon le test dependrait des
        # vraies annonces de la semaine, dont les gangs epuisent le budget.
        reseau["en_cache"] = {"ransomhouse"}
        doc, _ = _victime_ransomlook(db, "Exemple Defence Force", "ransomhouse")

        issue = svc.locate_victims(db, pause=lambda s: None)

        assert issue.located >= 1
        db.refresh(doc)
        assert doc.source_meta["victim_country"] == "NA"
        assert doc.source_meta["victim_domain"] == "defense-exemple.gov.na"
        assert doc.source_meta["victim_location_source"] == "ransomware.live"
        # Le gang d'origine est conserve.
        assert doc.source_meta["group_name"] == "ransomhouse"

    def test_une_victime_deja_localisable_par_son_domaine_est_ignoree(self, db, reseau):
        reseau["historiques"]["ransomhouse"] = [NDF]
        doc, _ = _victime_ransomlook(
            db,
            "Exemple Defence Force",
            "ransomhouse",
            detection_type="domain",
            valeur="defense-exemple.gov.na",
        )
        svc.locate_victims(db, pause=lambda s: None)
        db.refresh(doc)
        assert "victim_country" not in doc.source_meta

    def test_le_flux_des_victimes_recentes_suffit_sans_historique(self, db, reseau):
        reseau["recentes"] = [NDF]
        doc, _ = _victime_ransomlook(db, "Exemple Defence Force", "ransomhouse")
        svc.locate_victims(db, pause=lambda s: None)
        db.refresh(doc)
        assert doc.source_meta["victim_country"] == "NA"

    def test_les_appels_reseau_sont_bornes_et_espaces(self, db, reseau):
        """Rate limit ~1/min : au plus `max_gangs` appels, une pause entre
        chacun. Les historiques en cache ne comptent pas."""
        for gang in ("gangaaa", "gangbbb", "gangccc", "gangddd"):
            _victime_ransomlook(db, f"Victime {gang}", gang)
        reseau["en_cache"] = {"gangaaa"}
        pauses = []
        svc.locate_victims(db, max_gangs=2, pause=pauses.append)
        appeles = set(reseau["appels"])
        assert "gangaaa" in appeles  # en cache : toujours lu
        assert len(appeles - {"gangaaa"}) == 2  # 2 appels reseau, pas 3
        assert pauses == [svc.PAUSE_ENTRE_APPELS_S]


class TestPasseRegionale:
    def _localisee(self, db, titre, pays, domaine=None):
        doc, det = _victime_ransomlook(db, titre, "ransomhouse")
        doc.source_meta = {
            **doc.source_meta,
            "victim_country": pays,
            "victim_domain": domaine,
            "victim_location_source": "ransomware.live",
        }
        db.flush()
        return det

    def test_une_victime_localisee_en_afrique_produit_une_alerte_regionale(self, db):
        det = self._localisee(
            db, "Exemple Defence Force", "NA", "defense-exemple.gov.na"
        )
        alertes = generate_alerts(db, regions=["Afrique"])
        miennes = [
            a for a in alertes if any(ad.detection_id == det.id for ad in a.detections)
        ]
        assert len(miennes) == 1
        assert miennes[0].scope == "region" and miennes[0].region == "Afrique"

    def test_hors_du_perimetre_geographique_rien(self, db):
        det = self._localisee(db, "Acme Europe Holdings", "FR", "acme.fr")
        alertes = generate_alerts(db, regions=["Afrique"])
        assert not any(
            ad.detection_id == det.id for a in alertes for ad in a.detections
        )

    def test_une_organisation_surveillee_n_est_pas_non_declaree(self, db):
        """Meme faux positif que celui du 2026-09-04 : une victime surveillee
        ne doit pas revenir comme « victime non declaree »."""
        f.entity(db, domain="defense-exemple.gov.na")
        det = self._localisee(
            db, "Exemple Defence Force", "NA", "defense-exemple.gov.na"
        )
        alertes = generate_alerts(db, regions=["Afrique"])
        assert not any(
            ad.detection_id == det.id for a in alertes for ad in a.detections
        )
