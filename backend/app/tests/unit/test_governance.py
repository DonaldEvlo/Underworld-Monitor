"""Vue de gouvernance (RSSI) -- logique pure (pipeline/reporting/governance).

Verrouille ce que le tableau de direction doit dire HONNETEMENT : une mesure
absente reste absente (jamais 0), les mois vides restent dans la serie, et le
perimetre filtre bien la menace sectorielle."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.pipeline.reporting.governance import (
    AlertFact,
    VictimFact,
    sector_threat,
    service_activity,
    world_threat,
)

T0 = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)


def _alerte(**champs) -> AlertFact:
    base = dict(
        alert_date=date(2026, 9, 15), created_at=T0, severity="medium", status="open"
    )
    base.update(champs)
    return AlertFact(**base)


class TestActiviteDuService:
    def test_aucune_alerte_traitee_delais_non_mesurables(self):
        """⚠️ None, jamais 0 : « 0 h » dirait « traite instantanement »."""
        r = service_activity([_alerte(), _alerte(severity="critical")])
        assert r["median_hours_to_acknowledge"] is None
        assert r["median_hours_to_resolve"] is None
        assert r["false_positive_rate"] is None
        assert r["treated"] == 0

    def test_delais_medians_et_faux_positifs(self):
        alertes = [
            _alerte(acknowledged_at=T0 + timedelta(hours=2)),
            _alerte(acknowledged_at=T0 + timedelta(hours=6)),
            _alerte(
                status="resolved",
                resolved_at=T0 + timedelta(hours=10),
                resolution_reason="false_positive",
            ),
            _alerte(
                status="resolved",
                resolved_at=T0 + timedelta(hours=30),
                resolution_reason="confirmed",
            ),
        ]
        r = service_activity(alertes)
        assert r["median_hours_to_acknowledge"] == 4.0
        assert r["median_hours_to_resolve"] == 20.0
        assert r["false_positive_rate"] == 0.5

    def test_semaines_et_secteurs_nis2(self):
        r = service_activity(
            [
                _alerte(severity="critical", sector="Government & Defense"),
                _alerte(alert_date=date(2026, 9, 29), sector="Manufacturing"),
                _alerte(alert_date=date(2026, 9, 30)),
            ]
        )
        assert [s["week"] for s in r["weekly"]] == ["2026-09-14", "2026-09-28"]
        secteurs = {s["label"]: s for s in r["by_sector"]}
        assert secteurs["Government & Defense"]["critical"] is True
        assert (
            secteurs["Government & Defense"]["label_fr"] == "Administration et défense"
        )
        assert secteurs["Manufacturing"]["critical"] is False
        # « non renseigne » reste VISIBLE : le cacher gonflerait les autres parts.
        assert "non renseigne" in secteurs


class TestMenaceSectorielle:
    NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)

    def _continent(self, pays: str) -> str | None:
        return {"ZA": "Afrique", "NA": "Afrique", "FR": "Europe"}.get(pays)

    def _menace(self, victimes):
        return sector_threat(
            victimes,
            continent_de=self._continent,
            continents=("Afrique",),
            now=self.NOW,
            months=12,
        )

    def test_perimetre_et_fenetre(self):
        r = self._menace(
            [
                VictimFact(
                    datetime(2026, 9, 12, tzinfo=timezone.utc),
                    "ransomhouse",
                    "Government & Defense",
                    "NA",
                ),
                VictimFact(
                    datetime(2026, 9, 1, tzinfo=timezone.utc), "x", "Retail", "FR"
                ),
                # Hors fenetre de 12 mois.
                VictimFact(
                    datetime(2025, 8, 1, tzinfo=timezone.utc), "y", "Retail", "ZA"
                ),
            ]
        )
        assert r["total"] == 1
        assert r["critical_sector_share"] == 1.0
        assert r["by_gang"] == [{"label": "ransomhouse", "count": 1}]

    def test_mois_vides_gardes_dans_la_serie(self):
        """Un trou dans la serie se lirait comme une donnee manquante."""
        r = self._menace(
            [VictimFact(datetime(2026, 9, 12, tzinfo=timezone.utc), "g", None, "ZA")]
        )
        assert len(r["monthly"]) == 12
        assert r["monthly"][0]["month"] == "2025-10"
        assert r["monthly"][-1] == {
            "month": "2026-09",
            "critical_sector": 0,
            "other": 1,
        }
        assert sum(m["other"] + m["critical_sector"] for m in r["monthly"]) == 1

    def test_aucune_victime_part_non_mesurable(self):
        r = self._menace([])
        assert r["total"] == 0
        assert r["critical_sector_share"] is None


class TestMenaceMondiale:
    """Le monde entier, l'Afrique mise en avant mais jamais isolée (2026-10-03)."""

    NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)

    def _continent(self, pays: str) -> str | None:
        return {"ZA": "Afrique", "FR": "Europe", "US": "Amerique du Nord"}.get(pays)

    def _victime(
        self, pays, secteur="Retail", quand=datetime(2026, 9, 10, tzinfo=timezone.utc)
    ):
        return VictimFact(quand, "g", secteur, pays)

    def _monde(self, victimes):
        return world_threat(
            victimes,
            continent_de=self._continent,
            continents_mis_en_avant=("Afrique",),
            now=self.NOW,
        )

    def test_tous_les_continents_sont_comptes(self):
        r = self._monde(
            [
                self._victime("US"),
                self._victime("US"),
                self._victime("FR"),
                self._victime("ZA"),
            ]
        )
        assert r["total"] == 4
        # Le plus touché en tête.
        assert r["by_continent"][0]["label"] == "Amerique du Nord"
        assert {c["label"] for c in r["by_continent"]} == {
            "Amerique du Nord",
            "Europe",
            "Afrique",
        }

    def test_le_continent_surveille_est_signale_pas_isole(self):
        r = self._monde([self._victime("US"), self._victime("ZA")])
        signales = {c["label"]: c["highlighted"] for c in r["by_continent"]}
        assert signales == {"Amerique du Nord": False, "Afrique": True}

    def test_pays_inconnu_jamais_rattache_a_un_continent(self):
        r = self._monde([self._victime(None), self._victime("ZA")])
        assert {c["label"] for c in r["by_continent"]} == {"non renseigné", "Afrique"}

    def test_part_des_secteurs_critiques_par_continent(self):
        r = self._monde(
            [
                self._victime("ZA", "Healthcare"),
                self._victime("ZA", "Retail"),
                self._victime("FR"),
            ]
        )
        afrique = next(c for c in r["by_continent"] if c["label"] == "Afrique")
        assert afrique["critical_sector_share"] == 0.5
        assert afrique["share"] == round(2 / 3, 3)

    def test_hors_fenetre_exclu(self):
        vieille = datetime(2025, 8, 1, tzinfo=timezone.utc)
        assert self._monde([self._victime("US", quand=vieille)])["total"] == 0
