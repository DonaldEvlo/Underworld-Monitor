"""Rappels de progression de `check_onion_entries` (2026-09-11).

Aucun reseau : `_check_one`, `polite_delay` et `renew_circuit` sont remplaces.
Ce qui est verrouille : chaque adresse testee est signalee dans les DEUX
passes, le debut de la seconde passe est annonce, et un rappel defaillant ne
fait jamais echouer le test."""

import threading
from datetime import datetime, timezone

from app.pipeline.collect import onion_healthcheck as oh

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def _patch(monkeypatch, first_failures):
    """`first_failures` : URLs en echec a la 1re tentative, joignables ensuite."""
    vus: dict[str, int] = {}
    verrou = threading.Lock()

    def fake_check_one(name, url, timeout):
        with verrou:
            vus[url] = vus.get(url, 0) + 1
            tentative = vus[url]
        reachable = not (url in first_failures and tentative == 1)
        return oh.OnionCheckResult(
            name, url, reachable, 200 if reachable else None, NOW
        )

    renouvellements = []
    monkeypatch.setattr(oh, "_check_one", fake_check_one)
    monkeypatch.setattr(oh, "polite_delay", lambda: None)
    monkeypatch.setattr(oh, "renew_circuit", lambda: renouvellements.append(1))
    return renouvellements


class TestProgressCallbacks:
    def test_every_result_is_reported_in_both_passes(self, monkeypatch):
        renouvellements = _patch(monkeypatch, first_failures={"http://b.onion"})
        appels = []
        retries = []

        results = oh.check_onion_entries(
            [("A", "http://a.onion"), ("B", "http://b.onion")],
            on_result=lambda r, phase: appels.append((phase, r.url, r.reachable)),
            on_retry_start=retries.append,
        )

        premiere = {(u, ok) for phase, u, ok in appels if phase == "first"}
        seconde = [(u, ok) for phase, u, ok in appels if phase == "retry"]
        assert premiere == {("http://a.onion", True), ("http://b.onion", False)}
        assert retries == [1]
        assert seconde == [("http://b.onion", True)]
        assert renouvellements == [1]
        assert all(r.reachable for r in results)

    def test_no_retry_announced_when_everything_answers(self, monkeypatch):
        renouvellements = _patch(monkeypatch, first_failures=set())
        retries = []

        oh.check_onion_entries([("A", "http://a.onion")], on_retry_start=retries.append)

        assert retries == []
        assert renouvellements == []

    def test_failing_callback_never_breaks_the_check(self, monkeypatch):
        _patch(monkeypatch, first_failures={"http://b.onion"})

        def explose(*_args):
            raise RuntimeError("affichage indisponible")

        results = oh.check_onion_entries(
            [("A", "http://a.onion"), ("B", "http://b.onion")],
            on_result=explose,
            on_retry_start=explose,
        )

        assert {r.url for r in results} == {"http://a.onion", "http://b.onion"}

    def test_callbacks_are_optional(self, monkeypatch):
        """L'import GitHub appelle `check_onion_entries(candidates)` sans
        rappel : ce chemin ne doit pas changer."""
        _patch(monkeypatch, first_failures=set())

        results = oh.check_onion_entries([("A", "http://a.onion")])

        assert len(results) == 1
