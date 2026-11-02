"""Mode operatoire des gangs d'une alerte (service + route), sur base reelle
isolee (transaction annulee). L'appel a ransomware.live est simule : aucun
test ne sort du poste (regle 3)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.services import gang_profile_service as service
from app.tests.integration import factories as f

PROFIL_LOCKBIT = {
    "name": "lockbit3",
    "ttps": [
        {
            "tactic_id": "TA0001",
            "tactic_name": "Initial Access",
            "techniques": [
                {
                    "technique_id": "T1190",
                    "technique_name": "Exploit Public-Facing Application",
                    "technique_details": "Exploitation of CVE-2023-4966 (Citrix Bleed)",
                },
                {
                    # Identifiant hostile : ne doit JAMAIS devenir un lien.
                    "technique_id": "javascript:alert(1)",
                    "technique_name": "piege",
                },
            ],
        }
    ],
    "tools": ["Mimikatz"],
}


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def profils(monkeypatch):
    """gang -> reponse simulee. Absent = None (tiers injoignable)."""
    reponses: dict[str, list | None] = {}
    monkeypatch.setattr(service, "payload_rwl_profile", lambda gang: reponses.get(gang))
    return reponses


def _victime(db, gang: str, domaine: str | None = None):
    src = f.source(db)
    domaine = domaine or f"{f.unique('victime')}.co.za"
    doc = f.document(db, src, title=domaine)
    det = f.detection(db, doc, value_masked=domaine)
    det.corroborated_group = gang
    db.flush()
    return domaine, det


class TestModeOperatoire:
    def test_gang_documente(self, db, profils) -> None:
        domaine, det = _victime(db, "lockbit3")
        alerte = f.alert(db, [det], ent=f.entity(db, domain=domaine))
        profils["lockbit3"] = [PROFIL_LOCKBIT]

        (mo,) = service.modus_operandi(db, alerte)

        assert mo.status is service.ProfileStatus.DOCUMENTED
        assert mo.victims == (domaine,)
        assert "CVE-2023-4966" in mo.profile.cves
        assert mo.profile.tools == ("Mimikatz",)

    def test_gang_suivi_sans_ttp(self, db, profils) -> None:
        domaine, det = _victime(db, "krybit")
        alerte = f.alert(db, [det], ent=f.entity(db, domain=domaine))
        profils["krybit"] = []  # HTTP 404 : gang non documente

        (mo,) = service.modus_operandi(db, alerte)

        assert mo.status is service.ProfileStatus.UNDOCUMENTED

    def test_tiers_injoignable_n_efface_pas_les_autres_gangs(self, db, profils) -> None:
        """Absence de MESURE pour l'un, profil pour l'autre : les deux sont
        rendus, sans exception."""
        d1, det1 = _victime(db, "krybit")
        d2, det2 = _victime(db, "lockbit3")
        alerte = f.alert(db, [det1, det2], region=f.unique("Region-"))
        profils["lockbit3"] = [PROFIL_LOCKBIT]  # krybit : absent -> None

        statuts = {mo.gang: mo.status for mo in service.modus_operandi(db, alerte)}

        assert statuts == {
            "krybit": service.ProfileStatus.UNAVAILABLE,
            "lockbit3": service.ProfileStatus.DOCUMENTED,
        }

    def test_chaque_gang_ne_porte_que_SES_victimes(self, db, profils) -> None:
        """TEMOIN : alerte regionale, deux victimes de deux gangs. Sans le
        rattachement par victime, on ecrirait « krybit revendique Suivi Flotte »
        (erreur reelle du 2026-09-28)."""
        _, det1 = _victime(db, "krybit", "domaine-exemple.co.za")
        _, det2 = _victime(db, "direwolf", "suivi-flotte.co.za")
        alerte = f.alert(db, [det1, det2], region=f.unique("Region-"))
        profils["krybit"] = []
        profils["direwolf"] = []

        victimes = {mo.gang: mo.victims for mo in service.modus_operandi(db, alerte)}

        assert victimes == {
            "krybit": ("domaine-exemple.co.za",),
            "direwolf": ("suivi-flotte.co.za",),
        }


class TestRoute:
    @pytest.fixture
    def client(self, db):
        analyste = User(
            id=uuid.uuid4(), username="t_analyste", role="analyst", active=True
        )
        app.dependency_overrides[get_current_user] = lambda: analyste
        app.dependency_overrides[get_db] = lambda: db
        yield TestClient(app)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    def test_mise_en_garde_et_liens_surs(self, db, profils, client) -> None:
        domaine, det = _victime(db, "lockbit3")
        alerte = f.alert(db, [det], ent=f.entity(db, domain=domaine))
        profils["lockbit3"] = [PROFIL_LOCKBIT]

        corps = client.get(f"/api/alerts/{alerte.id}/modus-operandi").json()

        assert "ne dit PAS comment cette organisation" in corps["caveat"]
        (gang,) = corps["gangs"]
        urls = {t["technique_id"]: t["url"] for t in gang["techniques"]}
        assert urls["T1190"] == "https://attack.mitre.org/techniques/T1190/"
        assert urls["javascript:alert(1)"] is None
        assert gang["cves"] == [
            {
                "cve": "CVE-2023-4966",
                "url": "https://nvd.nist.gov/vuln/detail/CVE-2023-4966",
            }
        ]

    def test_alerte_inconnue_404(self, client) -> None:
        assert (
            client.get(f"/api/alerts/{uuid.uuid4()}/modus-operandi").status_code == 404
        )
