"""Tests de la validation de l'echelle de credibilite (phase 6). Logique pure."""

from __future__ import annotations

import pytest

from app.pipeline.evaluation.credibility_eval import (
    Observation,
    fisher_exact,
    mantel_haenszel,
    tableau,
)


class TestFisher:
    def test_valeur_de_reference_tea_tasting(self):
        """Exemple classique de Fisher [[3, 1], [1, 3]] : p bilateral = 0,486."""
        assert fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857, abs=1e-3)

    def test_tableau_tres_desequilibre_est_significatif(self):
        assert fisher_exact(10, 0, 0, 10) < 0.001

    def test_aucune_difference_p_egal_1(self):
        assert fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)

    def test_tableau_vide(self):
        assert fisher_exact(0, 0, 0, 0) == 1.0


class TestTableau:
    def test_taux_et_intervalle(self):
        obs = [Observation("g", "published", i < 2) for i in range(10)]
        ligne = next(line for line in tableau(obs) if line.status == "published")
        assert (ligne.total, ligne.press) == (10, 2)
        assert ligne.rate == pytest.approx(0.2)
        assert ligne.ci_low < 0.2 < ligne.ci_high

    def test_statut_vide_reste_affiche(self):
        """Un statut sans victime s'affiche a 0, il ne disparait pas."""
        statuts = {line.status for line in tableau([])}
        assert statuts == {"published", "pending", "unknown"}


class TestMantelHaenszel:
    def test_effet_de_gang_neutralise(self):
        """Paradoxe de Simpson : dans CHAQUE gang le statut n'a aucun effet,
        mais le gang le plus mediatise publie tout. Sans ajustement, on
        croirait a un effet du statut ; ajuste, le rapport vaut 1."""
        obs = []
        # Gang mediatise : 50 % de presse, publiees ET en attente.
        obs += [Observation("big", "published", i % 2 == 0) for i in range(80)]
        obs += [Observation("big", "pending", i % 2 == 0) for i in range(20)]
        # Gang discret : 0 % ... on met 10 % pour garder un contraste.
        obs += [Observation("small", "published", i < 2) for i in range(20)]
        obs += [Observation("small", "pending", i < 8) for i in range(80)]
        assert mantel_haenszel(obs)["odds_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_strate_sans_contraste_ignoree(self):
        obs = [Observation("tout_publie", "published", True) for _ in range(5)]
        resultat = mantel_haenszel(obs)
        assert resultat["odds_ratio"] is None
        assert resultat["strates_informatives"] == []

    def test_inconnu_hors_du_contraste(self):
        obs = [Observation("g", "unknown", True) for _ in range(5)]
        assert mantel_haenszel(obs)["strates_total"] == 0


class TestIntervalleDuRapportDeCotes:
    def test_une_strate_se_ramene_a_woolf(self):
        """Sur une seule strate, la variance de Robins-Breslow-Greenland vaut
        celle de Woolf : 1/a + 1/b + 1/c + 1/d."""
        import math

        obs = (
            [Observation("g", "published", True)] * 10
            + [Observation("g", "published", False)] * 20
            + [Observation("g", "pending", True)] * 5
            + [Observation("g", "pending", False)] * 40
        )
        resultat = mantel_haenszel(obs)
        assert resultat["odds_ratio"] == pytest.approx(4.0)
        marge = 1.96 * math.sqrt(1 / 10 + 1 / 20 + 1 / 5 + 1 / 40)
        assert resultat["ci_low"] == pytest.approx(math.exp(math.log(4) - marge))
        assert resultat["ci_high"] == pytest.approx(math.exp(math.log(4) + marge))

    def test_peu_de_cas_donne_un_intervalle_large(self):
        obs = (
            [Observation("g", "published", True)] * 2
            + [Observation("g", "published", False)] * 50
            + [Observation("g", "pending", True)] * 1
            + [Observation("g", "pending", False)] * 10
        )
        resultat = mantel_haenszel(obs)
        assert resultat["ci_low"] < 1 < resultat["ci_high"]
