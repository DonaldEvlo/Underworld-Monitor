"""Historique des revendications : republication ou attribution disputee.

Les cas reprennent la mesure du 2026-09-30 (voir claim_history.py) : ORION
republie des victimes LockBit jusqu'a trois ans apres ; beast et qilin publient
les memes victimes a quelques jours d'ecart."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.pipeline.alerting.claim_history import (
    REPUBLICATION_GAP_DAYS,
    ClaimHistory,
    classify_claims,
)

LOCKBIT = datetime(2023, 9, 16, tzinfo=timezone.utc)
ORION = datetime(2026, 8, 5, tzinfo=timezone.utc)


class TestRepublication:
    def test_notre_revendication_republie_une_fuite_plus_ancienne(self):
        """Document venu du site d'ORION : c'est LUI qui republie."""
        resultat = classify_claims("orion", {"orion": ORION, "lockbit3": LOCKBIT})
        assert resultat.republished_from == ("lockbit3", LOCKBIT)
        assert resultat.disputed_with == ()

    def test_nous_detenons_l_original_rien_a_signaler(self):
        """Document venu du site de LockBit : ORION republie APRES nous, ce
        qui ne dit rien de notre revendication."""
        assert (
            classify_claims("lockbit3", {"lockbit3": LOCKBIT, "orion": ORION})
            == ClaimHistory()
        )

    def test_on_retient_la_plus_ancienne_des_revendications_anterieures(self):
        plus_ancienne = LOCKBIT - timedelta(days=200)
        resultat = classify_claims(
            "orion",
            {"orion": ORION, "lockbit3": LOCKBIT, "akira": plus_ancienne},
        )
        assert resultat.republished_from == ("akira", plus_ancienne)


class TestAttributionDisputee:
    def test_publications_contemporaines(self):
        beast = datetime(2026, 9, 1, tzinfo=timezone.utc)
        resultat = classify_claims(
            "beast", {"beast": beast, "qilin": beast + timedelta(days=4)}
        )
        assert resultat.disputed_with == ("qilin",)
        assert resultat.republished_from is None

    def test_la_borne_de_la_fenetre_est_une_dispute(self):
        nous = datetime(2026, 9, 1, tzinfo=timezone.utc)
        pile = nous - timedelta(days=REPUBLICATION_GAP_DAYS)
        resultat = classify_claims("a", {"a": nous, "b": pile})
        assert resultat.disputed_with == ("b",)
        assert resultat.republished_from is None

    def test_juste_au_dela_c_est_une_republication(self):
        nous = datetime(2026, 9, 1, tzinfo=timezone.utc)
        avant = nous - timedelta(days=REPUBLICATION_GAP_DAYS + 1)
        assert classify_claims("a", {"a": nous, "b": avant}).republished_from == (
            "b",
            avant,
        )


class TestAbsenceDeMesure:
    def test_notre_date_inconnue_aucune_conclusion(self):
        """Ne pas avoir mesure n'est pas avoir constate une revendication
        unique."""
        assert (
            classify_claims("orion", {"orion": None, "lockbit3": LOCKBIT})
            == ClaimHistory()
        )

    def test_notre_gang_absent_aucune_conclusion(self):
        assert classify_claims("orion", {"lockbit3": LOCKBIT}) == ClaimHistory()

    def test_une_date_inconnue_chez_l_autre_est_ignoree(self):
        assert (
            classify_claims("orion", {"orion": ORION, "lockbit3": None})
            == ClaimHistory()
        )
