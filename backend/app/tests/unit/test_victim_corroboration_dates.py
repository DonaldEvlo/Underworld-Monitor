"""Dates d'annonces RansomLook avec et sans fuseau (bug reel du 2026-09-11).

La premiere passe reelle de la corroboration par victime a leve
`TypeError: can't compare offset-naive and offset-aware datetimes` : le flux
`/api/posts` date ses annonces avec un fuseau, certains historiques de gangs
sans. Les deux doivent cohabiter dans le meme index."""

from datetime import datetime, timezone

from app.pipeline.enrich.ransomlook_corroboration import (
    CorroborationStatus,
    VictimIndex,
    build_victim_index,
    corroborate_victim,
)


class TestDatesSansFuseau:
    def test_meme_gang_date_naive_puis_aware(self):
        index = VictimIndex()
        index.add("krybit", "acme.com", "2026-08-10 12:00:00.000000")
        index.add("krybit", "acme.com", "2026-08-03T00:00:00Z")
        (claim,) = index.by_domain["acme.com"]
        assert claim.discovered_at == datetime(2026, 8, 3, tzinfo=timezone.utc)

    def test_date_naive_lue_comme_utc(self):
        index = VictimIndex()
        index.add("akira", "Alder Millwork", "2026-08-10 12:00:00")
        (claim,) = index.by_name["alder millwork"]
        assert claim.discovered_at.tzinfo is not None

    def test_tri_de_gangs_aux_dates_heterogenes(self):
        index = build_victim_index(
            [],
            {
                "krybit": [
                    {"post_title": "acme.com", "discovered": "2026-08-10 12:00:00"}
                ],
                "nightspire": [
                    {"post_title": "acme.com", "discovered": "2026-08-01T00:00:00Z"}
                ],
                "qilin": [{"post_title": "acme.com", "discovered": None}],
            },
        )
        verdict = corroborate_victim(["acme.com"], [], index, expected_group="qilin")
        assert verdict.status is CorroborationStatus.CORROBORATED
        # Le gang de la source d'abord, puis par anciennete, les non dates en dernier.
        assert verdict.groups == ["qilin", "nightspire", "krybit"]
        assert verdict.first_seen_at == datetime(2026, 8, 1, tzinfo=timezone.utc)
