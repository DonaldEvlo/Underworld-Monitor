"""Corroboration par VICTIME (2026-09-11) -- logique pure, sans reseau ni base.

Ce qui est verrouille ici, ce sont les decisions mesurees le 2026-09-11 :
historique complet par gang, rapprochement par raison sociale borne au gang de
la source, revendications multiples conservees, perimetre « victimes
uniquement »."""

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.pipeline.enrich.ransomlook_corroboration import (
    Claim,
    CorroborationStatus,
    VictimIndex,
    build_victim_index,
    corroborate_victim,
    gang_slug_for_source,
    is_corroborable,
    name_key,
    parse_group_history,
)


def _d(jour: int) -> datetime:
    return datetime(2026, 8, jour, tzinfo=timezone.utc)


@dataclass
class FeedPost:
    group_name: str
    post_title: str
    discovered: str


class TestGangSlug:
    @pytest.mark.parametrize(
        "source, attendu",
        [
            ("LOCKBIT 3.0 (New Dark mirror 1) (DLS)", "lockbit3"),
            ("AKIRA (ransomware leak site)", "akira"),
            ("NIGHT SPIRE (DLS)", "nightspire"),
            ("DRAGON FORCE (DLS)", "dragonforce"),
            ("MYDATA / ALPHA LOCKER (DLS)", "mydata"),
            ("KRYBIT (DLS)", "krybit"),
        ],
    )
    def test_nom_de_source_vers_gang(self, source, attendu):
        assert gang_slug_for_source(source) == attendu

    def test_source_sans_nom(self):
        assert gang_slug_for_source(None) is None
        assert gang_slug_for_source("") is None


class TestPerimetreVictimesUniquement:
    def test_domaine_de_site_de_fuite_est_corroborable(self):
        assert is_corroborable("domain", "acme.com", "dls") is True

    def test_raison_sociale_de_site_de_fuite_est_corroborable(self):
        assert is_corroborable("organization", "Acme Industries", "akira") is True

    def test_domaine_cite_sur_un_forum_est_sans_objet(self):
        """Un domaine cite sur un forum n'est la victime de personne."""
        assert is_corroborable("domain", "acme.com", "xenforo_latest") is False

    def test_document_ransomlook_ne_se_confirme_pas_lui_meme(self):
        assert is_corroborable("domain", "acme.com", "ransomlook") is False

    def test_infrastructure_est_sans_objet(self):
        """69 % des domaines AKIRA etaient deux traqueurs BitTorrent."""
        assert is_corroborable("domain", "tracker.opentrackr.org", "akira") is False

    @pytest.mark.parametrize("valeur", ["abcdefghijklmnop.onion", "a***...", ""])
    def test_onion_tronque_ou_vide_est_sans_objet(self, valeur):
        assert is_corroborable("domain", valeur, "dls") is False

    def test_autres_types_ne_sont_jamais_confrontes(self):
        assert is_corroborable("email", "a***@acme.com", "dls") is False


class TestIndexGardeToutesLesRevendications:
    def test_deux_gangs_sur_le_meme_domaine(self):
        """Cas reel : `transports-exemple.com` chez NIGHT SPIRE ET KRYBIT."""
        index = VictimIndex()
        index.add("nightspire", "transports-exemple.com", _d(3))
        index.add("krybit", "www.transports-exemple.com", _d(5))
        assert {c.group_name for c in index.by_domain["transports-exemple.com"]} == {
            "nightspire",
            "krybit",
        }

    def test_meme_gang_deux_fois_garde_la_date_la_plus_ancienne_et_la_capture(self):
        index = VictimIndex()
        index.add("krybit", "acme.com", _d(9))
        index.add("krybit", "acme.com", _d(2), "screenshots/krybit/acmecom.png")
        (claim,) = index.by_domain["acme.com"]
        assert claim.discovered_at == _d(2)
        assert claim.screenshot_path == "screenshots/krybit/acmecom.png"

    def test_un_nom_n_est_pas_indexe_comme_domaine(self):
        index = VictimIndex()
        index.add("akira", "Alder Millwork", _d(1))
        assert index.by_domain == {}
        assert "alder millwork" in index.by_name


class TestDecisionParVictime:
    def _index(self):
        return build_victim_index(
            [FeedPost("l group", "quincaillerie-exemple.com", "2026-08-20T10:00:00Z")],
            {
                "krybit": [
                    {
                        "post_title": "www.quincaillerie-exemple.com",
                        "discovered": "2026-08-02T00:00:00Z",
                        "screen": "screenshots/krybit/ferretornilloscom.png",
                    },
                ],
                "akira": [
                    {
                        "post_title": "Propane Exemple Inc.",
                        "discovered": "2026-07-01T00:00:00Z",
                        "screen": None,
                    },
                ],
            },
        )

    def test_domaine_corrobore_avec_le_gang_de_la_source_en_premier(self):
        verdict = corroborate_victim(
            ["quincaillerie-exemple.com"], [], self._index(), expected_group="krybit"
        )
        assert verdict.status is CorroborationStatus.CORROBORATED
        assert verdict.match == "domain"
        assert verdict.groups == ["krybit", "l group"]

    def test_date_d_indexation_la_plus_ancienne(self):
        verdict = corroborate_victim(
            ["quincaillerie-exemple.com"], [], self._index(), expected_group="krybit"
        )
        assert verdict.first_seen_at == datetime(2026, 8, 2, tzinfo=timezone.utc)

    def test_preuve_par_victime_quand_la_capture_existe(self):
        verdict = corroborate_victim(
            ["quincaillerie-exemple.com"], [], self._index(), expected_group="krybit"
        )
        assert verdict.primary.evidence_url == (
            "https://www.ransomlook.io/screenshots/krybit/ferretornilloscom.png"
        )

    def test_raison_sociale_normalisee_dans_le_gang_de_la_source(self):
        verdict = corroborate_victim(
            [], ["PROPANE EXEMPLE"], self._index(), expected_group="akira"
        )
        assert verdict.status is CorroborationStatus.CORROBORATED
        assert verdict.match == "name"

    def test_meme_nom_chez_un_autre_gang_ne_suffit_pas(self):
        """Un nom n'a pas la structure d'un domaine : chez un autre gang, il
        peut designer une autre organisation."""
        verdict = corroborate_victim(
            [], ["Propane Exemple"], self._index(), expected_group="qilin"
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE

    def test_nom_sans_gang_de_source_ne_suffit_pas(self):
        verdict = corroborate_victim(
            [], ["Propane Exemple"], self._index(), expected_group=None
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE

    def test_egalite_jamais_inclusion(self):
        index = build_victim_index(
            [], {"akira": [{"post_title": "Acme", "discovered": None}]}
        )
        verdict = corroborate_victim(
            [], ["Acme County Sheriff"], index, expected_group="akira"
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE

    def test_sous_domaine_rejoint_le_domaine_par_labels(self):
        verdict = corroborate_victim(
            ["mail.quincaillerie-exemple.com"],
            [],
            self._index(),
            expected_group="krybit",
        )
        assert verdict.status is CorroborationStatus.CORROBORATED

    def test_domaine_sosie_ne_matche_pas(self):
        verdict = corroborate_victim(
            ["not-quincaillerie-exemple.com"],
            [],
            self._index(),
            expected_group="krybit",
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE

    def test_victime_inconnue_est_exclusive(self):
        verdict = corroborate_victim(
            ["inconnue.example"],
            ["Inconnue SA"],
            self._index(),
            expected_group="krybit",
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE
        assert verdict.groups == []


class TestNameKey:
    def test_domaine_n_est_pas_un_nom(self):
        assert name_key("acme.com") is None

    def test_nom_trop_court_refuse(self):
        assert name_key("ABC") is None

    def test_forme_juridique_retiree(self):
        assert name_key("Propane Exemple Inc.") == name_key("PROPANE-EXEMPLE, S.A.")


class TestHistorique:
    @pytest.mark.parametrize(
        "payload", [None, {}, [], [{}], [{}, "x"], [{}, [None, 3, {}]]]
    )
    def test_payload_inattendu_ne_leve_jamais(self, payload):
        assert parse_group_history(payload) == []

    def test_lit_titre_date_et_capture(self):
        (annonce,) = parse_group_history(
            [
                {"name": "krybit"},
                [
                    {
                        "post_title": " acme.com ",
                        "discovered": "2026-08-01",
                        "screen": "s/k/a.png",
                    }
                ],
            ]
        )
        assert annonce == {
            "post_title": "acme.com",
            "discovered": "2026-08-01",
            "screen": "s/k/a.png",
        }


class TestPreuveSansCapture:
    def test_repli_sur_la_page_du_gang(self):
        claim = Claim("the gentlemen", "acme.com", None)
        assert claim.evidence_url == "https://www.ransomlook.io/group/the%20gentlemen"


class TestFormesComposees:
    """ransomware.live ecrit parfois plusieurs domaines dans un champ, ou un
    schema mal forme. Compagnie Aérienne Exemple (2026-09-24) restait sans renseignements,
    donc en gravite `medium` au lieu de `critical`."""

    @pytest.mark.parametrize(
        ("champ", "attendu"),
        [
            (
                "compagnie-aerienne.co.tz / compagnie-aerienne.com",
                {"compagnie-aerienne.co.tz", "compagnie-aerienne.com"},
            ),
            ("www.a-b.com, www.c.com", {"a-b.com", "c.com"}),
            ("https//www.datanet.com", {"datanet.com"}),
            ("hhtps://library.mtroyal.ca", {"library.mtroyal.ca"}),
            ("https://www.partenaire-exemple.co.za/", {"partenaire-exemple.co.za"}),
            ("www.domaine-exemple.co.za", {"domaine-exemple.co.za"}),
        ],
    )
    def test_decoupe(self, champ, attendu):
        from app.pipeline.enrich.ransomlook_corroboration import domain_candidates

        assert domain_candidates(champ) == attendu

    @pytest.mark.parametrize(
        "champ",
        [
            "EXEMPLO, S.A. DE C.V",
            "TRANSPORTES Y LOGISTICA EXEMPLO, S.A",
            "Crowe",
            "S.A",
        ],
    )
    def test_raison_sociale_ne_devient_jamais_un_domaine(self, champ):
        """« S.A » (forme juridique) ne doit pas devenir le domaine `s.a`."""
        from app.pipeline.enrich.ransomlook_corroboration import domain_candidates

        assert domain_candidates(champ) == set()
