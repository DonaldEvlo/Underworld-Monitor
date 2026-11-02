"""Tests du service de test de disponibilite des sources.

Aucun test ne touche le reseau : `check_onion_entries` est monkeypatche.
Ce qui est verrouille ici, ce sont les DECISIONS du service, pas la mecanique
HTTP (deja couverte cote onion_healthcheck) : ne rien modifier en base, ne
perdre aucune source du rapport, respecter le plafond."""

import uuid
from datetime import datetime, timezone

from app.pipeline.collect.onion_healthcheck import OnionCheckResult
from app.services import source_health_service as svc
from app.services.source_health_service import check_sources

NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


class _FakeSource:
    def __init__(self, name, url, active=True, requires_js=False):
        self.id = uuid.uuid4()
        self.name = name
        self.url = url
        self.active = active
        self.requires_js = requires_js


class _FakeRepo:
    def __init__(self, sources):
        self._sources = sources
        self.get_active_called = False

    def list(self, limit=100):
        return self._sources[:limit]

    def get_active(self):
        self.get_active_called = True
        return [s for s in self._sources if s.active]


def _patch(monkeypatch, sources, results):
    repo = _FakeRepo(sources)
    monkeypatch.setattr(svc, "SourceRepository", lambda _db: repo)
    monkeypatch.setattr(svc, "check_onion_entries", lambda _entries, **_kw: results)
    return repo


def _result(url, reachable=True, status=200):
    return OnionCheckResult("n", url, reachable, status if reachable else None, NOW)


class TestCheckSources:
    def test_reports_reachable_and_unreachable(self, monkeypatch):
        sources = [
            _FakeSource("A", "http://a.onion"),
            _FakeSource("B", "http://b.onion"),
        ]
        _patch(
            monkeypatch,
            sources,
            [_result("http://a.onion"), _result("http://b.onion", reachable=False)],
        )

        report = check_sources(db=None)

        assert report.checked == 2
        assert report.reachable == 1
        assert report.unreachable == 1
        assert report.reachable_ratio == 0.5

    def test_empty_source_list_is_not_an_error(self, monkeypatch):
        _patch(monkeypatch, [], [])
        report = check_sources(db=None)
        assert report.checked == 0
        assert report.reachable_ratio == 0.0

    def test_only_active_uses_active_sources(self, monkeypatch):
        sources = [
            _FakeSource("A", "http://a.onion", active=True),
            _FakeSource("B", "http://b.onion", active=False),
        ]
        repo = _patch(monkeypatch, sources, [_result("http://a.onion")])

        report = check_sources(db=None, only_active=True)

        assert repo.get_active_called is True
        assert report.checked == 1

    def test_inactive_sources_are_tested_by_default(self, monkeypatch):
        """Une source desactivee est justement celle dont on veut savoir si
        elle est revenue en ligne."""
        sources = [_FakeSource("B", "http://b.onion", active=False)]
        _patch(monkeypatch, sources, [_result("http://b.onion")])

        report = check_sources(db=None)

        assert report.checked == 1
        assert report.items[0].active is False
        assert report.items[0].reachable is True

    def test_source_without_result_is_skipped_not_crashing(self, monkeypatch):
        """Un resultat manquant ne doit pas faire tomber le rapport entier."""
        sources = [
            _FakeSource("A", "http://a.onion"),
            _FakeSource("B", "http://b.onion"),
        ]
        _patch(monkeypatch, sources, [_result("http://a.onion")])

        report = check_sources(db=None)

        assert report.checked == 1
        assert [i.url for i in report.items] == ["http://a.onion"]

    def test_http_status_is_reported(self, monkeypatch):
        sources = [_FakeSource("A", "http://a.onion")]
        _patch(monkeypatch, sources, [_result("http://a.onion", status=403)])

        assert check_sources(db=None).items[0].http_status == 403


class TestNoSideEffects:
    """CONTRIBUTING.md : desactiver une source reste une decision de l'analyste.

    Une desactivation automatique sur un faux negatif (circuit Tor degrade)
    ferait perdre une source vivante silencieusement -- exactement le probleme
    que ce service cherche a rendre visible."""

    def test_unreachable_source_is_not_deactivated(self, monkeypatch):
        source = _FakeSource("A", "http://a.onion", active=True)
        _patch(monkeypatch, [source], [_result("http://a.onion", reachable=False)])

        check_sources(db=None)

        assert source.active is True

    def test_repo_has_no_write_method_called(self, monkeypatch):
        """Le faux repo n'expose ni update ni delete : si le service tentait
        d'ecrire, ce test leverait AttributeError."""
        sources = [_FakeSource("A", "http://a.onion")]
        _patch(monkeypatch, sources, [_result("http://a.onion", reachable=False)])

        check_sources(db=None)  # ne doit pas lever


class TestRequiresJsIsSurfaced:
    """Limite mesuree le 2026-08-21 : le test utilise `requests`, pas
    Playwright. Dread repondait `reachable=false` en `requests` (http ET
    https) le jour meme ou son collecteur ramenait 145 fils.

    `requires_js` doit donc remonter dans le rapport pour que l'interface
    puisse presenter un negatif comme NON CONCLUANT plutot que comme une
    source morte."""

    def test_requires_js_flag_is_reported(self, monkeypatch):
        sources = [_FakeSource("D", "http://d.onion", requires_js=True)]
        _patch(monkeypatch, sources, [_result("http://d.onion", reachable=False)])

        item = check_sources(db=None).items[0]

        assert item.requires_js is True
        assert item.reachable is False

    def test_plain_source_is_not_flagged(self, monkeypatch):
        sources = [_FakeSource("A", "http://a.onion")]
        _patch(monkeypatch, sources, [_result("http://a.onion")])

        assert check_sources(db=None).items[0].requires_js is False


def _refs(*urls, requires_js=False):
    return [
        svc.SourceRef(
            source_id=f"id-{i}",
            name=f"S{i}",
            url=u,
            active=True,
            requires_js=requires_js,
        )
        for i, u in enumerate(urls)
    ]


def _instantanes(snapshots):
    """La progression est un objet MUTABLE : on fige chaque publication."""

    def capture(progress):
        snapshots.append(
            (
                progress.phase,
                progress.first_pass_done,
                progress.retry_done,
                [e.state for e in progress.entries],
            )
        )

    return capture


class TestProgress:
    """Signale a l'usage le 2026-09-11 : un test de plusieurs minutes ne
    rendait AUCUN retour avant la fin. La progression doit etre publiee a
    chaque adresse, et la seconde passe (circuit renouvele) doit se voir."""

    def test_each_result_and_retry_are_published(self, monkeypatch):
        def fake_check(entries, *, on_result=None, on_retry_start=None):
            on_result(_result("http://a.onion"), "first")
            on_result(_result("http://b.onion", reachable=False), "first")
            on_retry_start(1)
            on_result(_result("http://b.onion"), "retry")
            return [_result("http://a.onion"), _result("http://b.onion")]

        monkeypatch.setattr(svc, "check_onion_entries", fake_check)
        snapshots = []

        report = svc.check_source_refs(
            _refs("http://a.onion", "http://b.onion"),
            on_progress=_instantanes(snapshots),
        )

        assert snapshots == [
            ("first_pass", 0, 0, ["pending", "pending"]),
            ("first_pass", 1, 0, ["reachable", "pending"]),
            ("first_pass", 2, 0, ["reachable", "unreachable"]),
            ("retry", 2, 0, ["reachable", "retrying"]),
            ("retry", 2, 1, ["reachable", "reachable"]),
            ("done", 2, 1, ["reachable", "reachable"]),
        ]
        assert report.reachable == 2

    def test_failed_retry_stays_unreachable_not_untested(self, monkeypatch):
        """Retestee sans succes : l'echec est acquis, ce n'est pas « non
        testee »."""

        def fake_check(entries, *, on_result=None, on_retry_start=None):
            on_result(_result("http://b.onion", reachable=False), "first")
            on_retry_start(1)
            on_result(_result("http://b.onion", reachable=False), "retry")
            return [_result("http://b.onion", reachable=False)]

        monkeypatch.setattr(svc, "check_onion_entries", fake_check)
        snapshots = []
        svc.check_source_refs(
            _refs("http://b.onion"), on_progress=_instantanes(snapshots)
        )

        assert snapshots[-1] == ("done", 1, 1, ["unreachable"])

    def test_source_without_any_result_ends_untested(self, monkeypatch):
        monkeypatch.setattr(svc, "check_onion_entries", lambda _e, **_kw: [])
        snapshots = []
        svc.check_source_refs(
            _refs("http://a.onion"), on_progress=_instantanes(snapshots)
        )

        assert snapshots[-1][3] == ["untested"]

    def test_failing_progress_callback_never_breaks_the_test(self, monkeypatch):
        """L'affichage est un confort ; le rapport reste le livrable."""

        def fake_check(entries, *, on_result=None, on_retry_start=None):
            on_result(_result("http://a.onion"), "first")
            return [_result("http://a.onion")]

        monkeypatch.setattr(svc, "check_onion_entries", fake_check)

        def explose(_progress):
            raise RuntimeError("Redis indisponible")

        report = svc.check_source_refs(_refs("http://a.onion"), on_progress=explose)

        assert report.checked == 1
        assert report.reachable == 1

    def test_load_sources_by_id_targets_only_those(self, monkeypatch):
        a = _FakeSource("A", "http://a.onion")
        b = _FakeSource("B", "http://b.onion")

        class _RepoParId(_FakeRepo):
            def get(self, id_):
                return next((s for s in self._sources if s.id == id_), None)

        repo = _RepoParId([a, b])
        monkeypatch.setattr(svc, "SourceRepository", lambda _db: repo)

        refs = svc.load_sources(db=None, source_ids=[str(b.id)])

        assert [r.url for r in refs] == ["http://b.onion"]


class TestLastSuccessfulCollection:
    """Signale a l'usage le 2026-09-11 : Dread paraissait en panne dans le
    test alors que sa collecte du jour avait ramene 85 documents. Pour une
    source qui exige un navigateur, le test HTTP simple n'est pas concluant :
    l'interface montre a cote la derniere collecte REUSSIE, qui doit donc
    voyager avec chaque source du test."""

    def test_last_collection_is_carried_to_entries(self, monkeypatch):
        quand = datetime(2026, 9, 11, 13, 51, tzinfo=timezone.utc)
        dread = _FakeSource("Dread", "http://d.onion", requires_js=True)
        dread.last_collected_at = quand
        monkeypatch.setattr(svc, "SourceRepository", lambda _db: _FakeRepo([dread]))
        echec = _result("http://d.onion", reachable=False)

        def fake_check(entries, *, on_result=None, on_retry_start=None):
            on_result(echec, "first")
            return [echec]

        monkeypatch.setattr(svc, "check_onion_entries", fake_check)
        snapshots = []

        svc.check_sources(
            db=None,
            on_progress=lambda p: snapshots.append(
                [(e.state, e.requires_js, e.last_collected_at) for e in p.entries]
            ),
        )

        assert snapshots[-1] == [("unreachable", True, quand)]

    def test_never_collected_source_has_no_date(self, monkeypatch):
        """Jamais collectee avec succes : aucune date, jamais une date inventee."""
        _patch(monkeypatch, [_FakeSource("A", "http://a.onion")], [])
        refs = svc.load_sources(db=None)
        assert refs[0].last_collected_at is None


class TestSafetyCap:
    def test_caps_number_of_sources_checked(self, monkeypatch):
        """Borne le trafic sortant meme si le nombre de sources grossit."""
        many = [_FakeSource(f"S{i}", f"http://s{i}.onion") for i in range(250)]
        results = [_result(f"http://s{i}.onion") for i in range(250)]
        _patch(monkeypatch, many, results)

        report = check_sources(db=None)

        assert report.checked == svc.MAX_SOURCES_CHECKED
