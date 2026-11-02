"""Qui frappe où : classement des groupes par région (2026-10-05)."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

from app.pipeline.reporting.governance import VictimFact
from app.pipeline.reporting.threat_actors import actors_by_region

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
CONTINENTS = {"ZA": "Afrique", "EG": "Afrique", "SN": "Afrique", "FR": "Europe"}


def _v(gang, pays, secteur=None, jour=datetime(2026, 9, 1, tzinfo=timezone.utc)):
    return VictimFact(discovered=jour, gang=gang, sector=secteur, country=pays)


def _calcul(victimes, **kw):
    return actors_by_region(
        victimes, continent_de=lambda c: CONTINENTS.get(c), now=NOW, **kw
    )


JEU = [
    _v("thegentlemen", "ZA", "Healthcare"),
    _v("thegentlemen", "EG"),
    _v("thegentlemen", "ZA"),
    _v("krybit", "SN", "Government & Defense"),
    _v("lockbit3", "FR"),
    _v("lockbit3", "FR"),
    _v("lockbit3", "FR"),
    _v("lockbit3", "FR"),
    _v("clop", None),
]


class TestClassement:
    def test_le_continent_filtre_et_classe(self):
        r = _calcul(JEU, continent="Afrique")
        assert [a["gang"] for a in r["actors"]] == ["thegentlemen", "krybit"]
        assert r["total"] == 4
        assert r["actors"][0]["share"] == 0.75
        assert r["actors"][0]["countries"][0] == {"code": "ZA", "count": 2}

    def test_monde_par_defaut(self):
        r = _calcul(JEU)
        assert r["actors"][0]["gang"] == "lockbit3"
        assert r["total"] == len(JEU)
        assert r["unknown_country"] == 1

    def test_le_pays_prime_sur_le_continent(self):
        r = _calcul(JEU, continent="Europe", country="za")
        assert r["country"] == "ZA"
        assert [a["gang"] for a in r["actors"]] == ["thegentlemen"]

    def test_hors_fenetre_ignore(self):
        vieille = _v("ancien", "ZA", jour=datetime(2024, 1, 1, tzinfo=timezone.utc))
        r = _calcul([vieille, *JEU], continent="Afrique")
        assert "ancien" not in {a["gang"] for a in r["actors"]}

    def test_sans_pays_jamais_rattache_a_un_continent(self):
        r = _calcul(JEU, continent="Afrique")
        assert "clop" not in {a["gang"] for a in r["actors"]}
        labels = {c["label"]: c["count"] for c in r["continents"]}
        assert labels["non renseigné"] == 1


class TestCouverture:
    def test_part_des_victimes_de_groupes_collectes(self):
        r = _calcul(JEU, continent="Afrique", collected={"krybit"})
        assert r["collected_victims"] == 1
        assert r["collected_share"] == 0.25
        drapeaux = {a["gang"]: a["collected"] for a in r["actors"]}
        assert drapeaux == {"thegentlemen": False, "krybit": True}

    def test_noms_normalises(self):
        r = _calcul([_v("The Gentlemen", "ZA")], collected={"thegentlemen"})
        assert r["actors"][0]["collected"] is True

    def test_region_vide(self):
        r = _calcul(JEU, continent="Oceanie")
        assert r["total"] == 0 and r["actors"] == []
        assert r["collected_share"] is None


def test_aucune_victime_nommee():
    """La frontière tient dans la forme : `VictimFact` n'a pas de nom."""
    assert {f.name for f in fields(VictimFact)} == {
        "discovered",
        "gang",
        "sector",
        "country",
    }
