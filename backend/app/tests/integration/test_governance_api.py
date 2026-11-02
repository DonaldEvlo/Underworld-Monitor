"""Routes de gouvernance, appelees EN RSSI (`viewer`) : c'est pour lui qu'elles
existent. Base reelle isolee ; le cache des historiques est simule."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.pipeline.reporting.governance import VictimFact
from app.services import governance_service
from app.tests.integration import factories as f


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def rssi(db, monkeypatch):
    monkeypatch.setattr(
        governance_service,
        "victimes_en_cache",
        lambda: (
            [
                VictimFact(
                    # Datee d'HIER : datee de l'instant de lecture, elle tomberait
                    # APRES le `now` fige par le service, donc hors fenetre.
                    datetime.now(timezone.utc) - timedelta(days=1),
                    "ransomhouse",
                    "Government & Defense",
                    "NA",
                )
            ],
            ["ransomhouse"],
        ),
    )
    viewer = User(id=uuid.uuid4(), username="t_rssi", role="viewer", active=True)
    app.dependency_overrides[get_current_user] = lambda: viewer
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestGouvernanceRssi:
    def test_le_rssi_voit_le_tableau(self, db, rssi) -> None:
        # Une victime au nom reperable : il ne doit JAMAIS sortir.
        _, _, _, _ = f.victime_alertee(db, source_name="GANGTEST (DLS)")

        reponse = rssi.get("/api/stats/governance")

        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["sector_threat"]["coverage_gangs"] == 1
        assert corps["sector_threat"]["total"] == 1
        assert corps["service"]["total"] >= 1
        # Agregats uniquement : ni valeur detectee, ni nom de document.
        assert "victime" not in reponse.text.lower().replace("victim_", "")
        assert "@" not in reponse.text

    def test_rapport_de_direction_pdf(self, rssi) -> None:
        reponse = rssi.get("/api/stats/governance/report.pdf?month=2026-09")

        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "application/pdf"
        assert "rapport-direction-2026-09.pdf" in reponse.headers["content-disposition"]
        assert reponse.content[:5] == b"%PDF-"

    @pytest.mark.parametrize("mauvais", ["2026-13", "septembre", "2026/09", ""])
    def test_mois_invalide_422(self, rssi, mauvais) -> None:
        assert (
            rssi.get(f"/api/stats/governance/report.pdf?month={mauvais}").status_code
            == 422
        )
