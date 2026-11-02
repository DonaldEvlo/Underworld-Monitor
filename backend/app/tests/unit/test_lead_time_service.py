"""Mesure d'avance : assemblage (reseau simule, aucune base)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.pipeline.evaluation.lead_time import OurVictim
from app.services.lead_time_service import (
    RANSOMLOOK,
    RANSOMWARE_LIVE,
    fresh_indexes,
    measure,
)

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
PREMIERES = {"KRYBIT (DLS)": T0 - timedelta(days=30)}


def _v(site: str) -> OurVictim:
    return OurVictim("KRYBIT (DLS)", "krybit", T0, (site,))


class TestMesure:
    def test_gang_non_suivi_n_est_pas_une_avance(self) -> None:
        """`{}` = l'observateur ne suit pas ce gang : sans cette exclusion,
        toutes ses victimes passeraient pour « nous en avance »."""
        index = {(RANSOMLOOK, "krybit"): {}, (RANSOMWARE_LIVE, "krybit"): None}
        obs, compteurs = measure(
            [_v("acme.co.za")], PREMIERES, index, T0 - timedelta(days=1), T0
        )
        assert obs == [] and compteurs["eligibles"] == 1

    def test_observateur_repondant_mesure(self) -> None:
        index = {(RANSOMLOOK, "krybit"): {"d:acme.co.za": T0 + timedelta(hours=4)}}
        obs, _ = measure(
            [_v("acme.co.za")], PREMIERES, index, T0 - timedelta(days=1), T0
        )
        assert len(obs) == 1 and obs[0].lead_hours == 4.0

    def test_rattrapage_exclu(self) -> None:
        premieres = {"KRYBIT (DLS)": T0}  # victime vue a la PREMIERE collecte
        index = {(RANSOMLOOK, "krybit"): {"d:acme.co.za": T0 + timedelta(hours=4)}}
        obs, compteurs = measure(
            [_v("acme.co.za")], premieres, index, T0 - timedelta(days=1), T0
        )
        assert obs == [] and compteurs["rattrapage_ou_hors_fenetre"] == 1


class TestAppelsFrais:
    def test_limite_de_debit_servie_en_200_puis_reessai(self) -> None:
        reponses = {
            "ransomlook": [
                [{}, [{"post_title": "acme.co.za", "discovered": "2026-09-27 13:00"}]]
            ],
            "rwl": [
                {"message": "1 per 1 minute"},
                [
                    {
                        "domain": "acme.co.za",
                        "victim": "Acme",
                        "discovered": "2026-09-27 14:00",
                    }
                ],
            ],
        }
        pauses: list[float] = []

        def fetch(url: str) -> object:
            cle = "rwl" if "ransomware.live" in url else "ransomlook"
            return reponses[cle].pop(0)

        index = fresh_indexes({"krybit"}, fetch=fetch, sleep=pauses.append)
        assert index[(RANSOMLOOK, "krybit")] == {
            "d:acme.co.za": T0 + timedelta(hours=1)
        }
        assert index[(RANSOMWARE_LIVE, "krybit")]["d:acme.co.za"] == T0 + timedelta(
            hours=2
        )
        assert len(pauses) == 1  # une seule pause : le reessai apres la limite

    def test_indisponible_devient_None_jamais_absent(self) -> None:
        def fetch(url: str) -> object:
            if "ransomware.live" in url:
                return {"message": "1 per 1 minute"}
            raise ConnectionError("hors ligne")

        index = fresh_indexes({"krybit"}, fetch=fetch, sleep=lambda s: None)
        assert index[(RANSOMLOOK, "krybit")] is None
        assert index[(RANSOMWARE_LIVE, "krybit")] is None


class TestRattrapageTardifService:
    def test_exclue_pour_tous_les_observateurs(self) -> None:
        """Si UN observateur prouve qu'elle existait avant notre collecte, la
        victime sort de la population des DEUX : on compare le meme ensemble."""
        index = {
            (RANSOMLOOK, "krybit"): {"d:acme.co.za": T0 - timedelta(days=400)},
            (RANSOMWARE_LIVE, "krybit"): {"d:acme.co.za": T0 + timedelta(hours=2)},
        }
        obs, compteurs = measure(
            [_v("acme.co.za")], PREMIERES, index, T0 - timedelta(days=1), T0
        )
        assert obs == []
        assert compteurs["rattrapage_tardif"] == 1 and compteurs["eligibles"] == 0
