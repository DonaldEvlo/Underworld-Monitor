"""Tests de l'echantillon de reference (logique pure, aucune base)."""

from collections import Counter

import pytest

from app.pipeline.evaluation.gold import (
    Candidate,
    Judged,
    cohen_kappa,
    draw_sample,
    evaluate,
    wilson,
)


def _corpus() -> list[Candidate]:
    """Forme du corpus reel : beaucoup de `leak` sur les sites de fuite,
    presque aucun `noise` (seul `contest.omg` chez LockBit)."""
    cands = []
    for i in range(300):
        cands.append(Candidate(f"vs-leak-{i}", "victim_site", "leak"))
    for i in range(200):
        cands.append(Candidate(f"fo-leak-{i}", "forum", "leak"))
    for i in range(2):
        cands.append(Candidate(f"vs-noise-{i}", "victim_site", "noise"))
    for i in range(400):
        cands.append(Candidate(f"fo-noise-{i}", "forum", "noise"))
    for i in range(50):
        cands.append(Candidate(f"vs-unc-{i}", "victim_site", "uncertain"))
    for i in range(80):
        cands.append(Candidate(f"fo-unc-{i}", "forum", "uncertain"))
    return cands


class TestDraw:
    def test_quotas_are_met(self):
        items = draw_sample(_corpus())
        par_verdict = Counter(i.sampled_verdict for i in items)
        assert par_verdict == {"leak": 60, "noise": 100, "uncertain": 40}

    def test_missing_kind_is_compensated_by_the_other(self):
        """Il n'y a que 2 `noise` sur les sites de fuite : les 48 manquants
        doivent venir des forums, sinon le quota `noise` serait ampute."""
        items = draw_sample(_corpus())
        strates = Counter(i.stratum for i in items)
        assert strates["victim_site:noise"] == 2
        assert strates["forum:noise"] == 98

    def test_same_seed_same_sample(self):
        """Un second tirage sur le meme corpus doit etre identique."""
        a = draw_sample(_corpus())
        b = draw_sample(list(reversed(_corpus())))
        assert [(i.document_id, i.rank) for i in a] == [
            (i.document_id, i.rank) for i in b
        ]

    def test_presentation_is_shuffled(self):
        """Les 20 premiers ne doivent pas etre d'une seule strate : presenter
        les `noise` a la suite installerait une attente chez l'annotateur."""
        items = sorted(draw_sample(_corpus()), key=lambda i: i.rank)
        assert len({i.stratum for i in items[:20]}) > 1

    def test_control_subset_has_its_own_order(self):
        items = draw_sample(_corpus())
        controle = [i for i in items if i.control_rank is not None]
        assert len(controle) == 50
        assert sorted(i.control_rank for i in controle) == list(range(1, 51))
        ordre_principal = [
            i.document_id for i in sorted(controle, key=lambda i: i.rank)
        ]
        ordre_controle = [
            i.document_id for i in sorted(controle, key=lambda i: i.control_rank)
        ]
        assert ordre_principal != ordre_controle

    def test_population_is_recorded_for_reweighting(self):
        items = draw_sample(_corpus())
        pop = {i.stratum: i.stratum_population for i in items}
        assert pop["forum:noise"] == 400
        assert pop["victim_site:leak"] == 300


class TestEvaluate:
    def test_uncertain_prediction_keeps_the_victim(self):
        """`uncertain` alimente la detection : ce n'est PAS une victime perdue."""
        r = evaluate([Judged("leak", "uncertain", "forum")])
        assert r.victim_retention.hits == 1
        assert r.costly == 0

    def test_noise_on_a_true_leak_is_the_costly_error(self):
        r = evaluate(
            [Judged("leak", "noise", "forum"), Judged("leak", "leak", "forum")]
        )
        assert r.costly == 1
        assert r.victim_retention.raw == pytest.approx(0.5)

    def test_human_uncertain_is_excluded_from_rates(self):
        """On ne reproche pas a un classifieur de mal trancher ce qu'un humain
        ne sait pas trancher."""
        r = evaluate(
            [Judged("uncertain", "noise", "forum"), Judged("noise", "noise", "forum")]
        )
        assert r.human_uncertain == 1
        assert r.accuracy.total == 1
        assert r.accuracy.hits == 1

    def test_abstention_is_counted_not_scored(self):
        r = evaluate([Judged("leak", None, "forum"), Judged("leak", "leak", "forum")])
        assert r.abstained == 1
        assert r.judged == 1

    def test_reweighting_changes_the_estimate(self):
        """Un item d'une strate sous-echantillonnee pese plus lourd : c'est
        tout l'objet du redressement."""
        items = [
            Judged("leak", "noise", "forum", weight=10.0),
            Judged("leak", "leak", "forum", weight=1.0),
        ]
        r = evaluate(items)
        assert r.victim_retention.raw == pytest.approx(0.5)
        assert r.victim_retention.weighted == pytest.approx(1 / 11)


class TestStatistics:
    def test_wilson_is_wider_on_small_samples(self):
        petit = wilson(8, 10)
        grand = wilson(80, 100)
        assert (petit[1] - petit[0]) > (grand[1] - grand[0])

    def test_wilson_empty(self):
        assert wilson(0, 0) == (0.0, 0.0)

    def test_kappa_perfect_agreement(self):
        assert cohen_kappa([("leak", "leak"), ("noise", "noise")]) == pytest.approx(1.0)

    def test_kappa_undefined_is_none_not_one(self):
        """Une seule etiquette employee partout : le kappa n'est pas defini.
        Rendre 1.0 afficherait une coherence parfaite qu'on n'a pas mesuree."""
        assert cohen_kappa([("leak", "leak"), ("leak", "leak")]) is None
        assert cohen_kappa([]) is None
