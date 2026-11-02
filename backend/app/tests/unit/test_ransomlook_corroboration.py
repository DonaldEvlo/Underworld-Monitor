"""Tests de la corroboration RansomLook (logique pure, aucun reseau).

Les donnees reproduisent le flux REEL releve le 2026-08-26 : titres tantot
domaine nu (`systemes-exemple.com`, `www.clinique-exemple.com.br`), tantot raison sociale
(`Crowe`, `Advanced Engineering Consultants`)."""

import pytest
from dataclasses import dataclass

from app.pipeline.enrich.ransomlook_corroboration import (
    group_evidence_api_url,
    parse_group_victim_evidence,
    CorroborationStatus,
    build_corroboration_index,
    corroborate_domain,
)


@dataclass(frozen=True)
class FakePost:
    """Reproduit `RansomLookPost` sans dependre du collecteur."""

    group_name: str
    post_title: str
    discovered: str


FEED = [
    FakePost("krybit", "www.partenaire-exemple.co.za", "2026-08-26T16:40:00Z"),
    FakePost("krybit", "systemes-exemple.com", "2026-08-26T17:10:00Z"),
    FakePost("qilin", "acme.com", "2026-08-20T09:00:00Z"),
    # Raison sociale : non corroborable (matching.py ne gere que DOMAIN/EMAIL)
    FakePost(
        "coinbase cartel", "Advanced Engineering Consultants", "2026-08-26T18:00:00Z"
    ),
    FakePost("the gentlemen", "Crowe", "2026-08-26T18:05:00Z"),
]


class TestIndexConstruction:
    def test_indexes_only_domain_like_titles(self):
        """Une raison sociale ne peut pas etre rattachee a une entite : elle
        ne doit pas polluer l'index."""
        index = build_corroboration_index(FEED)
        assert set(index) == {
            "partenaire-exemple.co.za",
            "systemes-exemple.com",
            "acme.com",
        }

    def test_strips_www_prefix(self):
        """KRYBIT publie `www.partenaire-exemple.co.za`, RansomLook `partenaire-exemple.co.za` :
        sans normalisation, les 3 victimes africaines communes ne seraient
        jamais rapprochees."""
        index = build_corroboration_index(FEED)
        assert "partenaire-exemple.co.za" in index
        assert "www.partenaire-exemple.co.za" not in index

    def test_keeps_most_recent_when_two_gangs_claim_the_same_victim(self):
        feed = [
            FakePost("old gang", "acme.com", "2026-08-01T00:00:00Z"),
            FakePost("new gang", "acme.com", "2026-08-25T00:00:00Z"),
        ]
        index = build_corroboration_index(feed)
        assert index["acme.com"].group_name == "new gang"

    def test_survives_missing_dates(self):
        """Une annonce sans date ne doit pas faire echouer l'indexation."""
        index = build_corroboration_index([FakePost("g", "acme.com", "")])
        assert index["acme.com"].discovered_at is None


class TestCorroboration:
    def test_exact_domain_is_corroborated(self):
        index = build_corroboration_index(FEED)
        status, match = corroborate_domain("systemes-exemple.com", index)
        assert status is CorroborationStatus.CORROBORATED
        assert match.group_name == "krybit"

    def test_www_variant_is_corroborated(self):
        """Notre detection porte `www.partenaire-exemple.co.za`, l'index
        `partenaire-exemple.co.za` -- meme organisation."""
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("www.partenaire-exemple.co.za", index)
        assert status is CorroborationStatus.CORROBORATED

    def test_subdomain_matches_parent(self):
        index = build_corroboration_index(FEED)
        status, match = corroborate_domain("mail.acme.com", index)
        assert status is CorroborationStatus.CORROBORATED
        assert match.group_name == "qilin"

    def test_lookalike_domain_is_not_corroborated(self):
        """⚠️ Comparaison par LABELS, jamais par sous-chaine (CONTRIBUTING.md §8) :
        `not-acme.com` contient bien « acme.com » en tant que texte."""
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("not-acme.com", index)
        assert status is CorroborationStatus.EXCLUSIVE

    def test_suffix_trap_is_not_corroborated(self):
        """`acme.com.evil.net` ne doit pas matcher `acme.com`."""
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("acme.com.evil.net", index)
        assert status is CorroborationStatus.EXCLUSIVE

    def test_unknown_domain_is_exclusive(self):
        """`exclusive` = nous seuls voyons cette victime. Ce n'est pas un
        defaut de fiabilite : nous lisons le DLS a la source."""
        index = build_corroboration_index(FEED)
        status, match = corroborate_domain("inconnue-totale.sn", index)
        assert status is CorroborationStatus.EXCLUSIVE
        assert match is None

    def test_empty_value_is_not_corroborated(self):
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("", index)
        assert status is CorroborationStatus.EXCLUSIVE

    def test_url_form_is_normalised(self):
        """Les DLS publient parfois `https://acme.com/` en guise de site."""
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("https://acme.com/", index)
        assert status is CorroborationStatus.CORROBORATED

    def test_case_and_trailing_dot_are_normalised(self):
        index = build_corroboration_index(FEED)
        status, _ = corroborate_domain("ACME.com.", index)
        assert status is CorroborationStatus.CORROBORATED


class TestEmptyFeed:
    """Un flux vide ne doit pas faire croire que tout est exclusif par
    erreur : c'est a l'appelant (service) de ne rien ecrire si la
    recuperation a echoue -- ici on verifie juste l'absence de crash."""

    def test_empty_feed_yields_exclusive(self):
        status, match = corroborate_domain("acme.com", {})
        assert status is CorroborationStatus.EXCLUSIVE
        assert match is None


class TestEvidenceUrl:
    """Une corroboration sans preuve consultable reste une affirmation.

    L'API `/api/posts` ne renvoie AUCUNE URL (3 champs seulement), mais la
    page `/group/<gang>` existe et **contient la victime** -- verifie le
    2026-08-26 sur `krybit` (partenaire-exemple, domaine-exemple, negoce-exemple,
    asa-international) et `safepay` (ferme-exemple, new-point)."""

    def test_builds_public_group_url(self):
        index = build_corroboration_index(FEED)
        _, match = corroborate_domain("systemes-exemple.com", index)
        assert match.evidence_url == "https://www.ransomlook.io/group/krybit"

    def test_url_is_clearnet_not_onion(self):
        """C'est tout l'interet face a notre propre URL de document : celle-ci
        est un .onion qui exige Tor, celle-la est consultable par un tiers."""
        index = build_corroboration_index(FEED)
        _, match = corroborate_domain("acme.com", index)
        assert match.evidence_url.startswith("https://www.ransomlook.io/")
        assert ".onion" not in match.evidence_url

    def test_group_with_space_is_escaped(self):
        """Des gangs reels ont un espace dans leur nom (`the gentlemen`,
        `inc ransom`) -- une URL brute serait invalide."""
        feed = [FakePost("the gentlemen", "acme.com", "2026-08-26T10:00:00Z")]
        index = build_corroboration_index(feed)
        _, match = corroborate_domain("acme.com", index)
        assert match.evidence_url == "https://www.ransomlook.io/group/the%20gentlemen"

    def test_no_url_without_group(self):
        feed = [FakePost("", "acme.com", "2026-08-26T10:00:00Z")]
        index = build_corroboration_index(feed)
        _, match = corroborate_domain("acme.com", index)
        assert match.evidence_url is None


class TestPreuveParVictime:
    """La corroboration doit pointer vers LA victime, pas vers le gang.

    ⚠️ Le lien precedent (`/group/<gang>`) est une page qui liste des centaines
    de victimes : l'analyste devait y chercher la sienne a la main. Une preuve
    qu'on ne peut pas consulter directement legitime mal une alerte.

    Mesure du 2026-09-04 avant d'en dependre : sur `krybit`, **136 posts sur
    136** portent un champ `screen`, et les URLs resolvent (HTTP 200,
    ~50 a 120 Ko).
    """

    def _payload(self):
        return [
            {"locations": [], "profile": []},
            [
                {
                    "post_title": "www.partenaire-exemple.co.za",
                    "screen": "screenshots/krybit/wwwpartenaireexemplecoza.png",
                    "link": "/blog/1c48e17/",
                    "discovered": "2026-08-02 16:50:13.730672",
                },
                {
                    "post_title": "www.institution-exemple.sn",
                    "screen": "/screenshots/krybit/wwwinstitutionexemplesn.png",
                    "link": "/blog/aa19665/",
                    "discovered": "2026-08-02 16:50:14.000000",
                },
                # Sans capture : ne doit rien produire plutot qu'une URL fausse.
                {"post_title": "sans-capture.com", "screen": "", "link": "/blog/x/"},
            ],
        ]

    def test_capture_par_victime_absolue(self):
        preuves = parse_group_victim_evidence(self._payload())
        assert (
            preuves["partenaire-exemple.co.za"]
            == "https://www.ransomlook.io/screenshots/krybit/wwwpartenaireexemplecoza.png"
        )

    def test_chemin_avec_ou_sans_barre_initiale(self):
        """RansomLook ecrit les deux formes dans le meme payload."""
        preuves = parse_group_victim_evidence(self._payload())
        assert preuves["institution-exemple.sn"].startswith(
            "https://www.ransomlook.io/screenshots/"
        )
        assert "//screenshots" not in preuves["institution-exemple.sn"]

    def test_victime_sans_capture_absente(self):
        """Mieux vaut retomber sur la page du gang qu'inventer une URL."""
        assert "sans-capture.com" not in parse_group_victim_evidence(self._payload())

    @pytest.mark.parametrize(
        "payload", [None, [], [{}], "texte", [{}, "pas une liste"]]
    )
    def test_payload_inattendu_ne_leve_jamais(self, payload):
        """⚠️ La corroboration est un enrichissement : elle ne doit jamais
        faire echouer l'alerting, qui est le livrable."""
        assert parse_group_victim_evidence(payload) == {}

    def test_url_de_l_api_du_gang_echappe_les_espaces(self):
        """Les gangs a espace (« the gentlemen », « inc ransom ») existent."""
        assert group_evidence_api_url("The Gentlemen").endswith(
            "/api/group/the%20gentlemen"
        )
