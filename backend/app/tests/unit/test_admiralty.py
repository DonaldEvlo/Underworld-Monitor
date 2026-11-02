"""Notation Admiralty -- logique pure."""

from __future__ import annotations

import pytest

from app.pipeline.alerting.admiralty import (
    TLP_RAPPORT,
    AdmiraltyRating,
    Grade,
    SourceTrack,
    best_source,
    information_credibility,
    source_reliability,
)


class TestFiabiliteDeLaSource:
    def test_jamais_A_meme_a_100_pourcent(self) -> None:
        """Un site de fuite publie des revendications d'ATTAQUANTS, et ceux
        qui le confirment lisent le meme site : B est le plafond."""
        assert source_reliability(SourceTrack(True, 974, 974)).valeur == "B"

    @pytest.mark.parametrize(
        ("evaluees", "confirmees", "attendu"),
        [
            (264, 250, "B"),  # APT73, 95 %
            (30, 19, "C"),  # ORION, 63 %
            (15, 15, "C"),  # 100 % mais moins de 20 victimes : pas B
            (40, 10, "D"),  # 25 %
            (9, 9, "F"),  # historique trop court
        ],
    )
    def test_seuils(self, evaluees: int, confirmees: int, attendu: str) -> None:
        assert (
            source_reliability(SourceTrack(True, evaluees, confirmees)).valeur
            == attendu
        )

    def test_forum_non_evaluable_et_non_mauvais(self) -> None:
        """F = « ne peut pas etre jugee », PAS E (« non fiable ») : un forum n'a
        pas d'historique mesurable par la corroboration."""
        note = source_reliability(SourceTrack(False, 0, 0))
        assert note.valeur == "F"
        assert "historique" in note.motif

    def test_le_motif_porte_les_chiffres(self) -> None:
        assert "250/264" in source_reliability(SourceTrack(True, 264, 250)).motif

    def test_meilleure_source(self) -> None:
        assert best_source([Grade("F", ""), Grade("B", ""), Grade("C", "")]) == Grade(
            "B", ""
        )
        assert best_source([]) is None


class TestCredibiliteDeLInformation:
    @pytest.mark.parametrize(
        ("niveau", "corrobore", "site", "attendu"),
        [
            ("confirmed", False, True, "1"),
            ("published", True, True, "2"),
            ("published", False, True, "3"),
            ("claimed", True, True, "3"),
            ("claimed", False, True, "3"),
            ("doubtful", True, True, "4"),
            ("claimed", False, False, "6"),  # forum
            (None, False, False, "6"),  # jamais evaluee
            ("not_evaluated", False, True, "6"),
        ],
    )
    def test_correspondance(
        self, niveau, corrobore, site, attendu
    ) -> None:  # noqa: ANN001
        assert information_credibility(niveau, corrobore, site).valeur == attendu

    def test_la_presse_prime_sur_tout(self) -> None:
        assert information_credibility("confirmed", False, False).valeur == "1"


class TestCode:
    def test_code_et_libelle(self) -> None:
        note = AdmiraltyRating(Grade("B", "m"), "KRYBIT (DLS)", Grade("2", "m"))
        assert note.code == "B2"
        assert note.libelle().startswith("B2 -- source habituellement fiable")
        assert "probablement vraie" in note.libelle()

    def test_tlp_du_rapport(self) -> None:
        """Le rapport s'adresse a la SEULE victime."""
        assert TLP_RAPPORT == "TLP:AMBER+STRICT"
