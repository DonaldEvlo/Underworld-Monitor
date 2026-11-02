"""Tests de pipeline/enrich/geo.py et pipeline/detect/infrastructure.py.

Ces deux modules servent le classement par continent et la carte des pays
touches. Ils sont purs : aucun reseau, aucune base.
"""

import pytest

from app.pipeline.detect.infrastructure import (
    is_infrastructure_domain,
    victim_domains,
)
from app.pipeline.enrich.geo import (
    continent_for_country,
    country_for_domain,
    locate_domain,
)


class TestInfrastructureIsNotAVictim:
    """Le cas fondateur : AKIRA est un groupe fiable, mais il joint un lien
    torrent a chaque annonce. 69 % de ses 2016 detections `domain` sont deux
    traqueurs BitTorrent. La fiabilite de la source et la qualite de notre
    extraction sont deux questions distinctes."""

    @pytest.mark.parametrize(
        "domaine",
        [
            "tracker.opentrackr.org",
            "tracker.openbittorrent.com",
            "t.me",
            "gmail.com",
            "mega.nz",
            "github.com",
            "rentry.co",
            "intelx.io",
        ],
    )
    def test_support_domains_are_infrastructure(self, domaine):
        assert is_infrastructure_domain(domaine) is True

    @pytest.mark.parametrize(
        "domaine",
        [
            "institution-exemple.sn",
            "domaine-exemple.co.za",
            "methodist-exemple.org.za",
            "fiducie-exemple.gov.co",
            "chimie-exemple.in",
        ],
    )
    def test_real_victims_are_kept(self, domaine):
        assert is_infrastructure_domain(domaine) is False

    @pytest.mark.parametrize(
        "domaine",
        [
            "check-host.net",
            "www.zone-h.org",
            "defacer.id",
            "youtu.be",
            "pixeldrain.com",
        ],
    )
    def test_outils_des_canaux_hacktivistes(self, domaine):
        """Mesure Telegram du 2026-09-26 : `check-host.net` (preuve de DDoS)
        est cite par 32 canaux ; les archives de defacement enregistrent la
        revendication -- la victime est le site defigure, pas l'archive."""
        assert is_infrastructure_domain(domaine) is True

    @pytest.mark.parametrize(
        "domaine",
        # Temoins : des noms PROCHES doivent rester des victimes possibles.
        ["host-check.net", "zone-h-bank.org", "riseupbank.net", "mycheck-host.net.ma"],
    )
    def test_les_noms_proches_restent_des_victimes(self, domaine):
        assert is_infrastructure_domain(domaine) is False

    def test_matching_is_by_label_suffix_not_substring(self):
        """Meme regle que le rattachement d'entite : comparer par sous-chaine
        ferait passer une vraie victime pour de l'infrastructure."""
        assert is_infrastructure_domain("mail.google.com") is True
        assert is_infrastructure_domain("notgoogle.com") is False
        assert is_infrastructure_domain("gmail.com.evil.net") is False

    def test_onion_is_always_infrastructure(self):
        """Aucune victime n'est designee par une adresse `.onion` : les 10
        `.onion` uniques du corpus sont tous des sources que nous collectons."""
        assert is_infrastructure_domain("darknet77von.onion") is True

    def test_truncated_value_is_not_guessed(self):
        assert is_infrastructure_domain("darknet7...wyad.onion") is True

    def test_victim_domains_preserves_order_and_duplicates(self):
        entree = ["acme.sn", "t.me", "acme.sn", "beta.ke"]
        assert victim_domains(entree) == ["acme.sn", "acme.sn", "beta.ke"]


class TestCountryFromDomain:
    @pytest.mark.parametrize(
        "domaine,pays",
        [
            ("institution-exemple.sn", "SN"),
            ("domaine-exemple.co.za", "ZA"),
            ("institut-exemple.ma", "MA"),
            ("finances-exemple.go.ke", "KE"),
            ("bbc.uk", "GB"),
            ("chimie-exemple.in", "IN"),
            ("automotores-exemple.com.ar", "AR"),
        ],
    )
    def test_cctld_gives_the_country(self, domaine, pays):
        assert country_for_domain(domaine) == pays

    @pytest.mark.parametrize(
        "domaine", ["acme.com", "beta.net", "gamma.org", "delta.xyz"]
    )
    def test_gtld_yields_no_country(self, domaine):
        """70 % du corpus. `None` signifie « aucun indice de pays », jamais
        « pays introuvable » -- ne pas en faire une categorie sur la carte."""
        assert country_for_domain(domaine) is None


class TestGenericCctldsAreNeverAttributed:
    """Verifie domaine par domaine sur le corpus reel : `.io` n'y contient
    qu'`apollo.io` / `etherscan.io` / `cracked.io`, `.to` que des forums de
    cracking, `.ly` que `bit.ly` et `sinister.ly`, `.me` que `telegram.me` et
    `wa.me`.

    Les attribuer mettrait les Tonga et le Montenegro parmi les pays les plus
    touches -- un chiffre techniquement exact et informativement faux, meme
    famille que le comptage sature d'IntelX."""

    @pytest.mark.parametrize(
        "domaine",
        [
            "cracked.to",
            "bit.ly",
            "telegram.me",
            "etherscan.io",
            "darkforums.su",
        ],
    )
    def test_generic_cctld_is_not_a_country(self, domaine):
        assert country_for_domain(domaine) is None


class TestTheColombianException:
    """`.co` est le seul cas mixte, et il se tranche sur la STRUCTURE.

    Ecarter tout `.co` perdrait de vraies institutions colombiennes (deux
    `.gov.co` dans le corpus) ; tout accepter ferait de la Colombie un faux
    pays majeur."""

    @pytest.mark.parametrize(
        "domaine",
        [
            "fiducie-exemple.gov.co",
            "www.sante-exemple.gov.co",
            "ecole-exemple.edu.co",
            "deportes-exemple.com.co",
        ],
    )
    def test_second_level_marks_a_real_colombian(self, domaine):
        assert country_for_domain(domaine) == "CO"

    @pytest.mark.parametrize("domaine", ["rentry.co", "ibb.co", "decrypt.co", "vrv.co"])
    def test_bare_co_is_generic(self, domaine):
        assert country_for_domain(domaine) is None


class TestContinent:
    @pytest.mark.parametrize(
        "pays,continent",
        [
            ("SN", "Afrique"),
            ("ZA", "Afrique"),
            ("MA", "Afrique"),
            ("FR", "Europe"),
            ("US", "Amerique du Nord"),
            ("AR", "Amerique du Sud"),
            ("IN", "Asie"),
            ("AU", "Oceanie"),
        ],
    )
    def test_maps_country_to_continent(self, pays, continent):
        assert continent_for_country(pays) == continent

    def test_unknown_country_has_no_continent(self):
        assert continent_for_country(None) is None
        assert continent_for_country("ZZ") is None

    def test_locate_returns_both_or_neither(self):
        assert locate_domain("institution-exemple.sn") == ("SN", "Afrique")
        assert locate_domain("acme.com") == (None, None)

    def test_every_mapped_country_has_a_continent(self):
        """Un pays sans continent disparaitrait silencieusement de tout
        regroupement : le classement par continent doit etre total."""
        from app.pipeline.enrich.geo import _CCTLD_TO_COUNTRY, _GENERIC_CCTLDS

        orphelins = [
            code
            for tld, code in _CCTLD_TO_COUNTRY.items()
            if tld not in _GENERIC_CCTLDS and continent_for_country(code) is None
        ]
        assert orphelins == []
