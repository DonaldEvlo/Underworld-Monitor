"""Pays DECLARE d'une victime publiee sans domaine (logique pure).

Cas fondateurs (2026-09-28) : « Exemple Defence Force » (ransomhouse),
« Exemple Insurance Group » et « Exemple Risk » (the gentlemen) -- en base, mais
jamais alertees faute de domaine localisable."""

from app.pipeline.enrich.ransomware_live import (
    group_profile_url,
    group_victims_url,
)
from app.pipeline.enrich.victim_location import (
    build_location_index,
    gangs_equivalents,
    locate_victim,
)

NDF = {
    "victim": "Exemple Defence Force",
    "domain": "www.defense-exemple.gov.na",
    "country": "NA",
}
EXEMPLE_RISK = {
    "victim": "Exemple Risk",
    "domain": "exemple-risk.co.za",
    "country": "ZA",
}


class TestUrlDuGang:
    """⚠️ Bug du 2026-09-29 : l'espace de « the gentlemen » partait dans
    l'URL, qui ne rendait rien -- tous les gangs a nom compose etaient muets."""

    def test_un_nom_compose_est_normalise(self):
        assert group_victims_url("the gentlemen").endswith("/groupvictims/thegentlemen")
        assert group_victims_url("inc ransom").endswith("/groupvictims/incransom")
        assert group_profile_url("the gentlemen").endswith("/group/thegentlemen")

    def test_un_nom_simple_est_inchange(self):
        assert group_victims_url("lockbit3").endswith("/groupvictims/lockbit3")
        assert group_victims_url("krybit").endswith("/groupvictims/krybit")


class TestGangsEquivalents:
    def test_graphies_differentes_du_meme_gang(self):
        assert gangs_equivalents("the gentlemen", "thegentlemen")
        assert gangs_equivalents("inc ransom", "incransom")
        assert gangs_equivalents("vexy", "Vexy Ransomware")

    def test_gangs_differents(self):
        assert not gangs_equivalents("krybit", "ransomhouse")
        assert not gangs_equivalents("lockbit3", "lockbit5")

    def test_prefixe_trop_court_refuse(self):
        assert not gangs_equivalents("inc", "incransom")

    def test_gang_absent(self):
        assert not gangs_equivalents(None, "krybit")
        assert not gangs_equivalents("", "")


class TestLocalisation:
    def test_victime_nommee_localisee_par_son_gang(self):
        index = build_location_index([("ransomhouse", NDF)])
        loc = locate_victim("Exemple Defence Force", "ransomhouse", index)
        assert loc is not None
        assert loc.country == "NA"
        assert loc.domain == "defense-exemple.gov.na"

    def test_le_meme_nom_chez_un_autre_gang_ne_localise_rien(self):
        """Borne au gang, comme la corroboration : un meme nom chez un autre
        gang peut designer une autre organisation."""
        index = build_location_index([("ransomhouse", NDF)])
        assert locate_victim("Exemple Defence Force", "krybit", index) is None

    def test_graphie_du_gang_differente_entre_agregateurs(self):
        index = build_location_index([("thegentlemen", EXEMPLE_RISK)])
        loc = locate_victim("Exemple Risk", "the gentlemen", index)
        assert loc is not None and loc.country == "ZA"

    def test_titre_qui_est_un_domaine(self):
        index = build_location_index([("thegentlemen", EXEMPLE_RISK)])
        loc = locate_victim("www.exemple-risk.co.za", "the gentlemen", index)
        assert loc is not None and loc.country == "ZA"

    def test_egalite_de_nom_jamais_inclusion(self):
        index = build_location_index([("thegentlemen", EXEMPLE_RISK)])
        assert (
            locate_victim("Exemple Risk Life Holdings", "thegentlemen", index) is None
        )

    def test_pays_ambigu_ne_localise_rien(self):
        """Une localisation fausse mettrait la victime dans le mauvais
        perimetre : pire qu'une victime non localisee."""
        index = build_location_index(
            [
                ("ransomhouse", {"victim": "Acme Holdings", "country": "NA"}),
                ("ransomhouse", {"victim": "Acme Holdings", "country": "FR"}),
            ]
        )
        assert locate_victim("Acme Holdings", "ransomhouse", index) is None

    def test_pays_invalide_ou_absent_ignore(self):
        index = build_location_index(
            [
                ("ransomhouse", {"victim": "Acme Holdings", "country": ""}),
                ("ransomhouse", {"victim": "Beta Holdings", "country": "Namibia"}),
            ]
        )
        assert locate_victim("Acme Holdings", "ransomhouse", index) is None
        assert locate_victim("Beta Holdings", "ransomhouse", index) is None

    def test_entree_avec_domaine_preferee(self):
        index = build_location_index(
            [
                ("ransomhouse", {"victim": "Acme Holdings", "country": "NA"}),
                (
                    "ransomhouse",
                    {
                        "victim": "Acme Holdings",
                        "country": "NA",
                        "domain": "acme.com.na",
                    },
                ),
            ]
        )
        loc = locate_victim("Acme Holdings", "ransomhouse", index)
        assert loc is not None and loc.domain == "acme.com.na"

    def test_pays_contredit_par_le_domaine_ne_localise_rien(self):
        """Cas reel : Exemple IVF declaree ZA avec un domaine `.co.id`
        (Indonesie) -- entree a tort dans l'alerte Afrique le 2026-09-29."""
        index = build_location_index(
            [
                (
                    "everest",
                    {
                        "victim": "Exemple IVF",
                        "country": "ZA",
                        "domain": "fertilite-exemple.co.id",
                    },
                )
            ]
        )
        assert locate_victim("Exemple IVF", "everest", index) is None

    def test_un_gtld_ne_contredit_rien(self):
        index = build_location_index(
            [
                (
                    "krybit",
                    {
                        "victim": "Exemple Logistics",
                        "country": "ZA",
                        "domain": "logistique-exemple.com",
                    },
                )
            ]
        )
        loc = locate_victim("logistique-exemple.com", "krybit", index)
        assert loc is not None and loc.country == "ZA"

    def test_nom_trop_court_ou_vide(self):
        index = build_location_index(
            [("ransomhouse", {"victim": "Abc", "country": "NA"})]
        )
        assert locate_victim("Abc", "ransomhouse", index) is None
        assert locate_victim(None, "ransomhouse", index) is None
        assert locate_victim("Exemple Defence Force", None, index) is None

    def test_entrees_mal_formees_toleres(self):
        index = build_location_index([("ransomhouse", "pas un dict"), ("x", None)])  # type: ignore[list-item]
        assert index == {}
