"""Mesure d'avance sur les agregateurs -- logique pure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.pipeline.evaluation.lead_time import (
    OurVictim,
    build_index,
    first_indexed,
    is_eligible,
    observe,
    summarize,
)

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _victime(termes=("acme.co.za",), vu=T0, source="KRYBIT (DLS)") -> OurVictim:
    return OurVictim(source=source, gang="krybit", first_seen=vu, terms=tuple(termes))


class TestIndex:
    def test_premiere_date_retenue(self) -> None:
        index = build_index(
            [
                {"post_title": "acme.co.za", "discovered": "2026-09-27 15:00:00"},
                {
                    "post_title": "www.acme.co.za",
                    "discovered": "2026-09-27T13:00:00+00:00",
                },
            ]
        )
        # `www.` normalise : les deux annonces designent la meme victime.
        assert first_indexed(["acme.co.za"], index) == T0 + timedelta(hours=1)

    def test_date_sans_fuseau_lue_en_UTC(self) -> None:
        index = build_index(
            [{"post_title": "acme.co.za", "discovered": "2026-09-27 12:00:00"}]
        )
        assert first_indexed(["acme.co.za"], index) == T0

    def test_annonce_sans_date_ignoree(self) -> None:
        assert build_index([{"post_title": "acme.co.za", "discovered": None}]) == {}

    def test_rapprochement_par_nom_a_egalite_jamais_par_inclusion(self) -> None:
        index = build_index(
            [
                {
                    "post_title": "Acme County Sheriff",
                    "discovered": "2026-09-27 12:00:00",
                }
            ]
        )
        assert first_indexed(["Acme"], index) is None
        index = build_index(
            [{"post_title": "Domaine Exemple", "discovered": "2026-09-27 12:00:00"}]
        )
        assert first_indexed(["Domaine Exemple Ltd"], index) == T0

    def test_domaine_par_labels(self) -> None:
        index = build_index(
            [{"post_title": "not-acme.co.za", "discovered": "2026-09-27 12:00"}]
        )
        assert first_indexed(["acme.co.za"], index) is None


class TestEligibilite:
    """Le biais du rattrapage : sans ce filtre, l'ecart median mesure le
    2026-09-15 etait de -329 jours, sans rien dire de notre reactivite."""

    def test_victime_de_la_premiere_collecte_exclue(self) -> None:
        v = _victime(vu=T0 + timedelta(minutes=5))
        assert is_eligible(v, source_first_collection=T0, window_start=T0) is False

    def test_victime_nouvelle_retenue(self) -> None:
        v = _victime(vu=T0 + timedelta(hours=6))
        assert is_eligible(v, source_first_collection=T0, window_start=T0) is True

    def test_hors_fenetre_exclue(self) -> None:
        v = _victime(vu=T0 + timedelta(hours=6))
        debut = T0 + timedelta(days=1)
        assert is_eligible(v, source_first_collection=T0, window_start=debut) is False


class TestObservation:
    def test_avance(self) -> None:
        index = build_index(
            [{"post_title": "acme.co.za", "discovered": "2026-09-27 17:00"}]
        )
        o = observe(_victime(), "RansomLook", index, now=T0 + timedelta(days=1))
        assert o.lead_hours == pytest.approx(5.0)
        assert not o.censored

    def test_retard(self) -> None:
        index = build_index(
            [{"post_title": "acme.co.za", "discovered": "2026-09-27 10:00"}]
        )
        o = observe(_victime(), "RansomLook", index, now=T0 + timedelta(days=1))
        assert o.lead_hours == pytest.approx(-2.0)

    def test_absente_chez_l_agregateur_est_censuree(self) -> None:
        """Ni « non appariee », ni « en retard » : une avance d'AU MOINS le
        temps ecoule."""
        o = observe(_victime(), "ransomware.live", {}, now=T0 + timedelta(hours=30))
        assert o.censored and o.lead_hours is None
        assert o.lower_bound_hours == pytest.approx(30.0)


class TestBilan:
    def _obs(self, ecarts, absentes=0):
        obs = []
        for i, e in enumerate(ecarts):
            index = build_index(
                [
                    {
                        "post_title": f"v{i}.co.za",
                        "discovered": (T0 + timedelta(hours=e)).isoformat(),
                    }
                ]
            )
            obs.append(
                observe(
                    _victime([f"v{i}.co.za"]), "RL", index, now=T0 + timedelta(days=2)
                )
            )
        for i in range(absentes):
            obs.append(
                observe(_victime([f"a{i}.co.za"]), "RL", {}, now=T0 + timedelta(days=2))
            )
        return obs

    def test_egalite_sous_la_resolution(self) -> None:
        s = summarize(self._obs([5.0, 1.0, -1.5, -8.0]), "RL", resolution_hours=3.0)
        assert (s.ahead, s.tied, s.behind) == (1, 2, 1)

    def test_censurees_hors_de_la_mediane(self) -> None:
        s = summarize(self._obs([2.0, 4.0], absentes=3), "RL", resolution_hours=3.0)
        assert s.measured == 2 and s.censored == 3 and s.eligible == 5
        assert s.median_lead_hours == pytest.approx(3.0)
        assert s.median_censored_lower_bound_hours == pytest.approx(48.0)

    def test_filtre_par_observateur(self) -> None:
        s = summarize(self._obs([2.0]), "ransomware.live", resolution_hours=3.0)
        assert s.eligible == 0 and s.median_lead_hours is None


class TestRattrapageTardif:
    """AKIRA donnait -401 jours a la premiere mesure reelle : des victimes
    anciennes vues tardivement, pas des retards."""

    def test_indexee_avant_notre_premiere_collecte_exclue(self) -> None:
        from app.pipeline.evaluation.lead_time import existed_before_collection

        index = build_index(
            [{"post_title": "acme.co.za", "discovered": "2025-08-01 00:00"}]
        )
        assert (
            existed_before_collection(_victime(), [index], T0 - timedelta(days=30))
            is True
        )

    def test_indexee_apres_retenue(self) -> None:
        from app.pipeline.evaluation.lead_time import existed_before_collection

        index = build_index(
            [{"post_title": "acme.co.za", "discovered": "2026-09-27 15:00"}]
        )
        assert (
            existed_before_collection(_victime(), [index], T0 - timedelta(days=30))
            is False
        )

    def test_absente_partout_retenue(self) -> None:
        from app.pipeline.evaluation.lead_time import existed_before_collection

        assert (
            existed_before_collection(_victime(), [{}], T0 - timedelta(days=30))
            is False
        )
