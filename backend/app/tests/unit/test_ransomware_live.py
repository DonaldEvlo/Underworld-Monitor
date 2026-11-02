"""ransomware.live comme SECOND observateur -- logique pure, sans reseau.

Verrouille : le parseur `groupvictims`, l'UNION des observateurs dans l'index,
la couverture d'un gang que RansomLook ignore, et la preuve par capture en URL
absolue."""

from app.pipeline.enrich.ransomlook_corroboration import (
    OBSERVER_RANSOMLOOK,
    OBSERVER_RANSOMWARE_LIVE,
    CorroborationStatus,
    build_victim_index,
    corroborate_victim,
)
from app.pipeline.enrich.ransomware_live import (
    group_victims_url,
    parse_group_victims,
    victim_metadata,
)

# Echantillon calque sur la reponse reelle (2026-09-14) : `domain` structure,
# `screenshot` en URL ABSOLUE, `victim` = raison sociale ou domaine.
_PAYLOAD = [
    {
        "victim": "www.boutique-exemple.com",
        "domain": "www.boutique-exemple.com",
        "discovered": "2026-09-13T12:29:33+00:00",
        "screenshot": "https://images.ransomware.live/victims/abc.png",
        "country": "AE",
        "activity": "Retail",
        "data_size": "40 GB",
    },
    {
        "victim": "Propane Exemple Inc.",
        "domain": "propanelevac.ca",
        "discovered": "2026-09-10T00:00:00+00:00",
        "screenshot": "",
        "country": "CA",
        "activity": "Manufacturing",
    },
]


class TestUrlAndParse:
    def test_url_uses_groupvictims_endpoint(self):
        assert group_victims_url("APT73") == (
            "https://api.ransomware.live/v2/groupvictims/apt73"
        )

    def test_emits_domain_and_distinct_name(self):
        annonces = parse_group_victims(_PAYLOAD)
        titres = {a["post_title"] for a in annonces}
        # domaine + domaine (1er : victim == domain, une seule entree) puis
        # domaine + raison sociale (2e victime).
        assert "www.boutique-exemple.com" in titres
        assert "propanelevac.ca" in titres
        assert "Propane Exemple Inc." in titres
        # Pas de doublon quand victim == domain.
        assert (
            titres.count("www.boutique-exemple.com")
            if isinstance(titres, list)
            else True
        )
        assert (
            sum(1 for a in annonces if a["post_title"] == "www.boutique-exemple.com")
            == 1
        )

    def test_screenshot_absolute_kept_empty_becomes_none(self):
        annonces = parse_group_victims(_PAYLOAD)
        par_titre = {a["post_title"]: a for a in annonces}
        assert par_titre["www.boutique-exemple.com"]["screen"] == (
            "https://images.ransomware.live/victims/abc.png"
        )
        assert par_titre["propanelevac.ca"]["screen"] is None

    def test_metadata_by_domain(self):
        meta = victim_metadata(_PAYLOAD)
        assert meta["boutique-exemple.com"]["country"] == "AE"
        assert meta["boutique-exemple.com"]["activity"] == "Retail"

    def test_tolerant_to_garbage(self):
        assert parse_group_victims(None) == []
        assert parse_group_victims({"x": 1}) == []
        assert parse_group_victims([1, "x", {}]) == []


class TestObserverUnion:
    def test_gang_only_on_ransomware_live_is_corroborated(self):
        """APT73 : RansomLook renvoie [] (ne le suit pas), ransomware.live a la
        victime. Elle doit etre corroboree, via le second observateur."""
        index = build_victim_index(
            [],
            {"apt73": []},  # RansomLook consulte, vide
            {OBSERVER_RANSOMWARE_LIVE: {"apt73": parse_group_victims(_PAYLOAD)}},
        )
        verdict = corroborate_victim(
            ["www.boutique-exemple.com"], [], index, expected_group="apt73"
        )
        assert verdict.status is CorroborationStatus.CORROBORATED
        assert verdict.observers == [OBSERVER_RANSOMWARE_LIVE]
        # Preuve = capture absolue de ransomware.live.
        assert verdict.primary.evidence_url == (
            "https://images.ransomware.live/victims/abc.png"
        )

    def test_two_observers_are_unioned(self):
        """Meme victime, meme gang, vue par les DEUX : une revendication, deux
        observateurs conserves."""
        index = build_victim_index(
            [],
            {
                "krybit": [
                    {
                        "post_title": "boutique-exemple.com",
                        "discovered": "2026-09-13T00:00:00Z",
                        "screen": None,
                    }
                ]
            },
            {OBSERVER_RANSOMWARE_LIVE: {"krybit": parse_group_victims(_PAYLOAD)}},
        )
        verdict = corroborate_victim(
            ["boutique-exemple.com"], [], index, expected_group="krybit"
        )
        assert verdict.status is CorroborationStatus.CORROBORATED
        assert verdict.observers == [OBSERVER_RANSOMLOOK, OBSERVER_RANSOMWARE_LIVE]
        # Un seul gang malgre deux observateurs.
        assert verdict.groups == ["krybit"]

    def test_exclusive_has_no_observers(self):
        index = build_victim_index(
            [], {"krybit": []}, {OBSERVER_RANSOMWARE_LIVE: {"krybit": []}}
        )
        verdict = corroborate_victim(
            ["inconnu.example"], [], index, expected_group="krybit"
        )
        assert verdict.status is CorroborationStatus.EXCLUSIVE
        assert verdict.observers == []
