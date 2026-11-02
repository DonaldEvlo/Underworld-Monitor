"""Route d'export STIX 2.1 d'une alerte, sur base reelle isolee (transaction
annulee). Le tiers (profil de gang) est simule : aucun appel reseau."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.alert_access import AlertAccess
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.services import gang_profile_service
from app.tests.integration import factories as f

PROFIL = {
    "name": "krybit",
    "ttps": [
        {
            "tactic_id": "TA0001",
            "tactic_name": "Initial Access",
            "techniques": [
                {
                    "technique_id": "T1190",
                    "technique_name": "Exploit Public-Facing Application",
                }
            ],
        }
    ],
    "tools": [{"Exfiltration": ["RClone"]}],
}


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(
        gang_profile_service, "payload_rwl_profile", lambda gang: [PROFIL]
    )
    # L'utilisateur existe en base : le journal d'acces le reference.
    analyste = User(
        id=uuid.uuid4(),
        username=f.unique("t_analyste_"),
        password_hash="x",
        role="analyst",
        active=True,
    )
    db.add(analyste)
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: analyste
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), analyste
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _alerte(db):
    src = f.source(db)
    domaine = f"{f.unique('victime')}.co.za"
    doc = f.document(db, src, title=domaine)
    det = f.detection(db, doc, value_masked=domaine)
    det.corroborated_group = "krybit"
    # Une adresse masquee rattachee a la meme alerte : elle ne doit JAMAIS
    # sortir dans le paquet (regle 2).
    adresse = f.detection(db, doc, type_="email", value_masked=f"j***@{domaine}")
    db.flush()
    alerte = f.alert(db, [det, adresse], ent=f.entity(db, domain=domaine))
    return alerte, domaine


class TestExportStix:
    def test_fichier_telecharge_et_acces_journalise(self, db, client) -> None:
        http, analyste = client
        alerte, domaine = _alerte(db)

        reponse = http.get(f"/api/alerts/{alerte.id}/stix.json")

        assert reponse.status_code == 200
        assert reponse.headers["content-type"].startswith("application/stix+json")
        assert "attachment" in reponse.headers["content-disposition"]
        assert ".json" in reponse.headers["content-disposition"]
        paquet = reponse.json()
        assert paquet["type"] == "bundle"
        noms = {o.get("name") for o in paquet["objects"]}
        assert {domaine, "krybit", "RClone"} <= noms
        # ⚠️ Le document SORT de l'outil : l'acces est trace (regle 5).
        acces = (
            db.query(AlertAccess)
            .filter(AlertAccess.alert_id == alerte.id, AlertAccess.action == "export")
            .all()
        )
        assert [a.username for a in acces] == [analyste.username]

    def test_aucune_valeur_detectee_ne_sort(self, db, client) -> None:
        http, _ = client
        alerte, _ = _alerte(db)

        texte = http.get(f"/api/alerts/{alerte.id}/stix.json").text

        assert "@" not in texte
        assert ".onion" not in texte

    def test_paquet_valide_par_le_validateur_officiel(self, db, client) -> None:
        validator = pytest.importorskip("stix2validator")
        http, _ = client
        alerte, _ = _alerte(db)

        paquet = json.loads(http.get(f"/api/alerts/{alerte.id}/stix.json").text)

        assert validator.validate_instance(paquet).is_valid

    def test_alerte_inconnue_404(self, client) -> None:
        http, _ = client
        assert http.get(f"/api/alerts/{uuid.uuid4()}/stix.json").status_code == 404
