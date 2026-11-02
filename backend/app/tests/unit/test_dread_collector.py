"""Tests du collecteur Dread (listing de subdreads + corps du 1er post).

Aucun test ne touche le reseau : `_fetch_search_html` est toujours
monkeypatche. Le HTML reproduit la structure REELLE observee sur /d/leaks le
2026-08-19 (carte de profil au survol incluse — c'est elle qui piege le
selecteur de date, voir TestListingParsing.test_ignores_author_join_date)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.source import SourceContract, SourceType
from app.pipeline.collect.dread import scraper as dread_scraper
from app.pipeline.collect.dread.adapter import DreadCollector, is_dread_url
from app.pipeline.collect.dread.scraper import (
    DEFAULT_MAX_PAGES,
    DreadThread,
    build_subdread_url,
    fetch_subdread_threads,
    parse_subdread_listing,
    parse_thread_body,
    parse_thread_date,
)

BASE = "http://dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion/"

# Structure reelle : la carte de profil (.dataCard) contient la date
# d'INSCRIPTION de l'auteur, a ne pas confondre avec la date du fil.
LISTING_HTML = """
<div class="postBoard">
  <div class="item">
    <div class="crosspost-heading">Shared by <a href="/u/rmrf">/u/rmrf</a> in <a href="/d/leaks">/d/leaks</a></div>
    <div class="postTop">
      <div class="author">by <span class="card">
        <a class="author_link" href="/u/seller99">seller99</a>
        <div class="dataCard user">
          <div>Joined<span title="April 15th, 2025">1 year ago</span></div>
        </div>
      </span></div>
      <a class="title" href="/post/abc123">Restauration-exemple.fr - Database LeakDownload</a>
      <span title="27th December, 2025 - 02:13">6 months ago</span>
      <span title="Edited 5 months ago">*</span>
      <span title="Sticky"></span>
      <div>39 comments</div>
    </div>
  </div>
  <div class="item">
    <div class="postTop">
      <a class="title" href="/post/def456">Australian Data dumpOffer</a>
      <a class="author_link" href="/u/vendor">vendor</a>
      <span title="18th August, 2026 - 09:00">yesterday</span>
      <div>2 comments</div>
    </div>
  </div>
  <div class="item">aucun lien /post/, doit etre ignore</div>
</div>
"""

THREAD_HTML = """
<html><body>
  <div class="postBoard">
    <div class="item">
      <div class="postContent">Full database of example-victim.sn, 120k rows, contact admin@example-victim.sn</div>
    </div>
  </div>
  <div class="commentBody">nice, still up?</div>
</body></html>
"""


def _source() -> SourceContract:
    return SourceContract(
        id=uuid.uuid4(),
        name="Dread",
        url=BASE,
        type=SourceType.FORUM,
        active=True,
        created_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )


class TestIsDreadUrl:
    def test_matches_dread_onion(self):
        assert is_dread_url(BASE) is True

    def test_rejects_other_onion(self):
        assert is_dread_url("http://someotherforum.onion/") is False


class TestBuildSubdreadUrl:
    def test_first_page_has_no_query(self):
        assert build_subdread_url(BASE, "leaks", 1).endswith("/d/leaks")

    def test_following_pages_use_p_param(self):
        assert build_subdread_url(BASE, "leaks", 3).endswith("/d/leaks?p=3")


class TestParseThreadDate:
    @pytest.mark.parametrize(
        "text,expected",
        [
            # Format REEL des listings de subdread (jour avant mois), releve
            # sur /d/leaks le 2026-08-19.
            ("24th January, 2026 - 02:13", datetime(2026, 1, 24, tzinfo=timezone.utc)),
            ("1st August, 2026", datetime(2026, 8, 1, tzinfo=timezone.utc)),
            # Format de la page de recherche (mois avant jour).
            ("December 27th, 2025", datetime(2025, 12, 27, tzinfo=timezone.utc)),
            ("May 3, 2026", datetime(2026, 5, 3, tzinfo=timezone.utc)),
        ],
    )
    def test_parses_dread_date_formats(self, text, expected):
        assert parse_thread_date(text) == expected

    def test_relative_date_returns_none(self):
        """Dread affiche aussi "3 hours ago" : mieux vaut pas de date qu'une
        date fausse (le document reste collecte)."""
        assert parse_thread_date("3 hours ago") is None

    def test_garbage_returns_none(self):
        assert parse_thread_date("") is None
        assert parse_thread_date("Foovember 40th, 2026") is None


class TestListingParsing:
    def test_extracts_threads(self):
        threads = parse_subdread_listing(LISTING_HTML, BASE)
        assert [t.title for t in threads] == [
            "Restauration-exemple.fr - Database Leak",
            "Australian Data dump",
        ]

    def test_ignores_items_without_post_link(self):
        assert len(parse_subdread_listing(LISTING_HTML, BASE)) == 2

    def test_strips_interface_suffix_from_title(self):
        """Dread colle "Download"/"Crosspost" au libelle du lien, sans separateur."""
        assert parse_subdread_listing(LISTING_HTML, BASE)[0].title.endswith("Leak")

    def test_links_are_absolute(self):
        assert all(
            t.thread_url.startswith(BASE)
            for t in parse_subdread_listing(LISTING_HTML, BASE)
        )

    def test_ignores_author_join_date(self):
        """Piege reel : `.dataCard` contient "Joined <span title='April 15th,
        2025'>". Prendre le premier span[title] venu daterait tous les fils a
        la date d'inscription de leur auteur."""
        first = parse_subdread_listing(LISTING_HTML, BASE)[0]
        assert first.published_at == datetime(2025, 12, 27, tzinfo=timezone.utc)

    def test_ignores_non_date_title_attributes(self):
        """Les span[title] "Edited ...", "Sticky", "Archived" cohabitent avec
        la date dans le meme item : prendre le premier venu donnerait None."""
        threads = parse_subdread_listing(LISTING_HTML, BASE)
        assert threads[0].published_at == datetime(2025, 12, 27, tzinfo=timezone.utc)
        assert threads[1].published_at == datetime(2026, 8, 18, tzinfo=timezone.utc)

    def test_strips_offer_suffix(self):
        assert (
            parse_subdread_listing(LISTING_HTML, BASE)[1].title
            == "Australian Data dump"
        )

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("/d/darknet", "darknet"),
            ("/d/DataBrokers", "DataBrokers"),
            ("/d/doxbin", "doxbin"),
            ("darknet", "darknet"),
            ("", ""),
        ],
    )
    def test_subdread_prefix_stripped_without_eating_letters(self, label, expected):
        """Regression : `lstrip("/d/")` retire tous les caracteres de
        l'ensemble {'/', 'd'}, donc "/d/darknet" devenait "arknet" — constate
        en base sur une collecte reelle le 2026-08-20. Les subdreads commencant
        par 'd' etaient silencieusement corrompus."""
        assert dread_scraper._strip_subdread_prefix(label) == expected

    def test_extracts_author_and_comment_count(self):
        first = parse_subdread_listing(LISTING_HTML, BASE)[0]
        assert first.author == "seller99"
        assert first.comment_count == 39

    def test_missing_board_returns_empty(self):
        assert parse_subdread_listing("<html>rien</html>", BASE) == []


class TestThreadBodyParsing:
    def test_extracts_first_post_only(self):
        """Le corps du post initial porte le signal ; les commentaires sont
        du bavardage — meme choix que exilio404/mybb_latest."""
        body = parse_thread_body(THREAD_HTML)
        assert "example-victim.sn" in body
        assert "still up?" not in body

    def test_missing_content_returns_none(self):
        assert parse_thread_body("<html><body>rien</body></html>") is None

    def test_excludes_comments_and_profile_card(self):
        """Structure reelle d'une page de fil : le post est le 1er `.item`,
        les commentaires sont des `.commentBody`, et `.dataCard` porte le
        score et la date d'inscription de l'auteur."""
        html = """
        <div class="postBoard">
          <div class="item">
            <div class="dataCard user"><div class="score">732 points</div>
              <div>Joined<span title="April 15th, 2025">1 year ago</span></div></div>
            120k rows from example-victim.sn
            <div class="commentBody">nice, still up?</div>
          </div>
        </div>
        """
        body = parse_thread_body(html)
        assert "example-victim.sn" in body
        assert "still up?" not in body
        assert "732 points" not in body
        assert "Joined" not in body


class TestPartialRenderGuard:
    """Mesure du 2026-08-19 : trois appels sur la MEME URL de fil ont renvoye
    1129 o, 17 559 o puis 91 805 o — Playwright rend la main avant que Dread
    ait fini d'injecter le contenu. Sans garde-fou, un corps vide etait
    enregistre comme un fait acquis (2 corps vides sur 3 fils constates)."""

    def test_partial_page_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            dread_scraper,
            "_fetch_search_html",
            lambda _u: "<html><head><title>Un fil - Dread</title></head><body></body></html>",
        )
        assert dread_scraper.fetch_thread_body(f"{BASE}post/abc") is None

    def test_partial_render_is_retried_until_complete(self, monkeypatch):
        """Coeur du correctif : un rendu partiel est un SUCCES du point de vue
        de tenacity (chaine valide), donc jamais rejoue par `@with_retry`.
        Mesure du 2026-08-19 : 1 tentative sur 3 exploitable sur /d/leaks —
        sans re-essai, deux collectes sur trois repartaient les mains vides et
        `collect_source` concluait a tort « source injoissable ou vide »."""
        pages = iter(["<html></html>", "<html></html>", THREAD_HTML])
        monkeypatch.setattr(dread_scraper, "_fetch_search_html", lambda _u: next(pages))
        body = dread_scraper.fetch_thread_body(f"{BASE}post/abc")
        assert body is not None and "example-victim.sn" in body

    def test_gives_up_after_max_attempts(self, monkeypatch):
        calls = {"n": 0}

        def _always_partial(_u):
            calls["n"] += 1
            return "<html></html>"

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _always_partial)
        assert dread_scraper.fetch_thread_body(f"{BASE}post/abc") is None
        assert calls["n"] == 3

    def test_anti_bot_page_is_not_retried(self, monkeypatch):
        """Une page anti-bot est complete, pas partielle : la rejouer ne ferait
        qu'insister sur un site qui vient de nous freiner."""
        calls = {"n": 0}

        def _anti_bot(_u):
            calls["n"] += 1
            return "<html>DDOS Protection</html>"

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _anti_bot)
        assert dread_scraper.fetch_thread_body(f"{BASE}post/abc") is None
        assert calls["n"] == 1

    def test_listing_also_retries_partial_render(self, monkeypatch):
        """Le garde-fou ne protegeait que les corps : les listings passaient au
        travers, d'ou des cycles a 0 document."""
        pages = iter(["<html></html>", LISTING_HTML, "<html></html>", "<html></html>"])
        monkeypatch.setattr(
            dread_scraper, "_fetch_search_html", lambda _u: next(pages, "<html></html>")
        )
        threads = dread_scraper.fetch_subdread_threads(
            BASE, "leaks", max_pages=1, fetch_bodies=False
        )
        assert len(threads) == 2

    def test_fully_rendered_page_is_accepted(self, monkeypatch):
        monkeypatch.setattr(dread_scraper, "_fetch_search_html", lambda _u: THREAD_HTML)
        assert "example-victim.sn" in dread_scraper.fetch_thread_body(f"{BASE}post/abc")

    def test_anti_bot_page_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            dread_scraper,
            "_fetch_search_html",
            lambda _u: "<html>DDOS Protection</html>",
        )
        assert dread_scraper.fetch_thread_body(f"{BASE}post/abc") is None

    def test_fetch_exception_returns_none(self, monkeypatch):
        def _boom(_u):
            raise RuntimeError("tor down")

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _boom)
        assert dread_scraper.fetch_thread_body(f"{BASE}post/abc") is None


class TestFetchSubdreadThreads:
    def test_stops_on_anti_bot_page(self, monkeypatch):
        """CONTRIBUTING.md : on ne tente JAMAIS de *resoudre* l'anti-bot (pas de
        captcha joue). On retente une fois sur un autre circuit Tor, puis on
        abandonne -- voir TestAntiBotRetriesOnNewCircuit.

        `renew_circuit` et `polite_delay` sont neutralises : sans cela ce test
        ouvrait une vraie connexion au port de controle Tor (constate via un
        DeprecationWarning de `stem`), ce qu'aucun test unitaire ne doit faire."""
        monkeypatch.setattr(dread_scraper, "renew_circuit", lambda: None)
        monkeypatch.setattr(dread_scraper, "polite_delay", lambda: None)
        monkeypatch.setattr(
            dread_scraper,
            "_fetch_search_html",
            lambda _u: "<html>DDOS Protection</html>",
        )
        assert fetch_subdread_threads(BASE, "leaks", fetch_bodies=False) == []

    def test_stops_on_empty_page(self, monkeypatch):
        monkeypatch.setattr(
            dread_scraper, "_fetch_search_html", lambda _u: "<html></html>"
        )
        assert fetch_subdread_threads(BASE, "leaks", fetch_bodies=False) == []

    def test_fetch_failure_does_not_raise(self, monkeypatch):
        def _boom(_u):
            raise RuntimeError("tor down")

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _boom)
        assert fetch_subdread_threads(BASE, "leaks", fetch_bodies=False) == []

    def test_respects_max_pages(self, monkeypatch):
        """Fraicheur incrementale, pas crawl historique (CONTRIBUTING.md regle 1)."""
        calls: list[str] = []

        def _fake(url):
            calls.append(url)
            # Chaque page sert des liens distincts pour ne pas court-circuiter
            # la boucle via la deduplication.
            return LISTING_HTML.replace("/post/abc123", f"/post/p{len(calls)}").replace(
                "/post/def456", f"/post/q{len(calls)}"
            )

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _fake)
        fetch_subdread_threads(BASE, "leaks", max_pages=3, fetch_bodies=False)
        assert len(calls) == 3

    def test_default_max_pages_is_incremental(self):
        """Fraicheur incrementale : 1 page = 20 fils par subdread, au-dela du
        volume publie entre deux cycles. Pas un crawl historique."""
        assert DEFAULT_MAX_PAGES == 1

    def test_stops_when_pagination_repeats(self, monkeypatch):
        """Si la pagination reboucle sur la meme page, on s'arrete au lieu de
        tourner jusqu'au plafond de securite."""
        calls: list[str] = []

        def _same(url):
            calls.append(url)
            return LISTING_HTML

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _same)
        threads = fetch_subdread_threads(
            BASE, "leaks", max_pages=10, fetch_bodies=False
        )
        assert len(threads) == 2
        assert len(calls) == 2

    def test_fetches_bodies_when_requested(self, monkeypatch):
        def _fake(url):
            return THREAD_HTML if "/post/" in url else LISTING_HTML

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _fake)
        threads = fetch_subdread_threads(BASE, "leaks", max_pages=1, fetch_bodies=True)
        assert all("example-victim.sn" in (t.body or "") for t in threads)


class TestAntiBotRetriesOnNewCircuit:
    """L'anti-bot de Dread est ALEATOIRE, pas structurel.

    Mesure sur deux cycles reels : /d/leaks et /d/hacking ont rendu 0 fil le
    2026-08-19 (anti-bot) puis 20 fils chacun le 2026-08-20, a position
    identique dans DEFAULT_SUBDREADS. C'est l'IP de sortie qui compte, pas
    l'ordre -- d'ou un NEWNYM + UNE retentative avant d'abandonner."""

    @staticmethod
    def _no_delay(monkeypatch):
        monkeypatch.setattr(dread_scraper, "polite_delay", lambda: None)

    def test_recovers_after_circuit_renewal(self, monkeypatch):
        self._no_delay(monkeypatch)
        renewed = {"n": 0}
        monkeypatch.setattr(
            dread_scraper, "renew_circuit", lambda: renewed.__setitem__("n", 1)
        )
        pages = iter(["<html>DDOS Protection</html>", LISTING_HTML])
        monkeypatch.setattr(dread_scraper, "_fetch_search_html", lambda _u: next(pages))

        threads = dread_scraper.fetch_subdread_threads(
            BASE, "leaks", max_pages=1, fetch_bodies=False
        )
        assert renewed["n"] == 1
        assert len(threads) == 2

    def test_gives_up_when_anti_bot_persists(self, monkeypatch):
        """UNE seule retentative : au-dela on martelerait un site qui vient de
        nous freiner (OPSEC, CONTRIBUTING.md §2.3)."""
        self._no_delay(monkeypatch)
        monkeypatch.setattr(dread_scraper, "renew_circuit", lambda: None)
        calls = {"n": 0}

        def _always_anti_bot(_u):
            calls["n"] += 1
            return "<html>DDOS Protection</html>"

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _always_anti_bot)
        threads = dread_scraper.fetch_subdread_threads(
            BASE, "leaks", max_pages=1, fetch_bodies=False
        )
        assert threads == []
        # 1 fetch initial + 1 seule retentative apres NEWNYM.
        assert calls["n"] == 2

    def test_circuit_renewal_failure_is_not_fatal(self, monkeypatch):
        """Un controlleur Tor injoignable ne doit pas faire remonter
        d'exception : le subdread est abandonne, les autres continuent."""
        self._no_delay(monkeypatch)

        def _boom():
            raise RuntimeError("control port down")

        monkeypatch.setattr(dread_scraper, "renew_circuit", _boom)
        monkeypatch.setattr(
            dread_scraper,
            "_fetch_search_html",
            lambda _u: "<html>DDOS Protection</html>",
        )
        assert (
            dread_scraper.fetch_subdread_threads(
                BASE, "leaks", max_pages=1, fetch_bodies=False
            )
            == []
        )

    def test_no_renewal_when_page_is_fine(self, monkeypatch):
        """Pas de NEWNYM gratuit : changer de circuit sans raison consomme du
        temps et modifie le profil de trafic pour rien."""
        self._no_delay(monkeypatch)
        renewed = {"n": 0}
        monkeypatch.setattr(
            dread_scraper, "renew_circuit", lambda: renewed.__setitem__("n", 1)
        )
        monkeypatch.setattr(
            dread_scraper, "_fetch_search_html", lambda _u: LISTING_HTML
        )

        dread_scraper.fetch_subdread_threads(
            BASE, "leaks", max_pages=1, fetch_bodies=False
        )
        assert renewed["n"] == 0


class TestBodyBudget:
    """Le budget de corps existe pour tenir sous `task_time_limit` (35 min).

    Mesure du 2026-08-19 : ~34 s par corps. Sans plafond, 8 subdreads x 20
    fils = ~90 min, donc tache tuee puis REJOUEE en boucle par Celery
    (`task_acks_late=True`) sans jamais aboutir — CONTRIBUTING.md §8."""

    def test_budget_limits_body_fetches(self, monkeypatch):
        calls: list[str] = []

        def _fake(url):
            calls.append(url)
            return THREAD_HTML

        monkeypatch.setattr(dread_scraper, "_fetch_search_html", _fake)
        threads = [
            DreadThread(title=f"T{i}", thread_url=f"{BASE}post/{i}") for i in range(10)
        ]
        result = dread_scraper._with_bodies(threads, budget=3)

        assert len(calls) == 3
        assert sum(1 for t in result if t.body) == 3

    def test_threads_beyond_budget_are_kept_without_body(self, monkeypatch):
        """Un fil hors budget reste collecte : son titre porte deja du signal."""
        monkeypatch.setattr(dread_scraper, "_fetch_search_html", lambda _u: THREAD_HTML)
        threads = [
            DreadThread(title=f"T{i}", thread_url=f"{BASE}post/{i}") for i in range(5)
        ]
        result = dread_scraper._with_bodies(threads, budget=2)

        assert len(result) == 5
        assert [t.title for t in result] == [f"T{i}" for i in range(5)]
        assert all(t.body is None for t in result[2:])

    def test_order_is_preserved_despite_parallel_fetch(self, monkeypatch):
        """Les corps sont recuperes en parallele (as_completed -> ordre
        d'arrivee non deterministe), mais la liste retournee doit rester dans
        l'ordre du listing : le plus recent d'abord."""
        monkeypatch.setattr(
            dread_scraper,
            "fetch_thread_body",
            lambda url: f"corps de {url.rsplit('/', 1)[-1]}",
        )
        threads = [
            DreadThread(title=f"T{i}", thread_url=f"{BASE}post/{i}") for i in range(8)
        ]
        result = dread_scraper._with_bodies(threads, budget=None)

        assert [t.title for t in result] == [f"T{i}" for i in range(8)]
        assert all(t.body == f"corps de {i}" for i, t in enumerate(result))

    def test_body_failure_does_not_break_the_batch(self, monkeypatch):
        """Une exception sur un fil ne doit pas faire tomber tout le lot."""

        def _flaky(url):
            if url.endswith("2"):
                raise RuntimeError("playwright crash")
            return "ok"

        monkeypatch.setattr(dread_scraper, "fetch_thread_body", _flaky)
        threads = [
            DreadThread(title=f"T{i}", thread_url=f"{BASE}post/{i}") for i in range(4)
        ]
        result = dread_scraper._with_bodies(threads, budget=None)

        assert len(result) == 4
        assert result[2].body is None
        assert [t.body for t in result if t.body] == ["ok", "ok", "ok"]

    def test_parallelism_is_bounded(self):
        """Aligne sur DREAD_SEARCH_MAX_WORKERS : meme site, meme cout memoire
        par navigateur. Monter sans remesurer rapprocherait du martelage."""
        assert dread_scraper.BODY_FETCH_WORKERS == 5

    def test_default_budget_stays_under_celery_limit(self):
        """Le budget doit tenir dans `soft_time_limit` de la tache Dread.

        Reference les limites REELLES de `dread_tasks` (75 min souple) plutot
        qu'une valeur ecrite en dur : la version precedente de ce test
        comparait aux 30 min *globales* de l'app, alors que la tache Dread a
        ses propres limites -- il verrouillait donc une contrainte plus stricte
        que la vraie.

        Cout mesure le 2026-08-20 apres parallelisation : ~15 s/corps. On
        double pour couvrir le pire cas observe (25 % de rendus partiels)."""
        from app.worker.tasks.dread_tasks import _SOFT_TIME_LIMIT_SECONDS

        measured_seconds_per_body = 15
        listings_overhead = 5 * 60
        worst_case = (
            dread_scraper.DEFAULT_MAX_BODIES * measured_seconds_per_body * 2
            + listings_overhead
        )
        assert worst_case < _SOFT_TIME_LIMIT_SECONDS

    def test_budget_is_global_not_per_subdread(self, monkeypatch):
        """Un budget applique par subdread laisserait le dernier subdread sans
        aucun corps une fois le temps consomme."""
        monkeypatch.setattr(
            dread_scraper,
            "fetch_subdread_threads",
            lambda _b, sub, _p, fetch_bodies=False: [
                DreadThread(title=f"{sub}-{i}", thread_url=f"{BASE}post/{sub}{i}")
                for i in range(3)
            ],
        )
        monkeypatch.setattr(dread_scraper, "_fetch_search_html", lambda _u: THREAD_HTML)

        result = dread_scraper.fetch_dread_threads(
            BASE, subdreads=("a", "b"), max_bodies=4
        )
        assert len(result) == 6
        assert sum(1 for t in result if t.body) == 4


class TestInteractiveVsScheduledBudget:
    """Le budget de corps differe selon le declencheur.

    A pleine charge (100 corps) un cycle dure ~24 min : acceptable la nuit,
    pas devant un analyste qui a clique « Collecter tout » — d'autant que
    Dread monopoliserait l'un des 5 workers du batch pendant que les autres
    sources rendent en ~1 min."""

    def test_interactive_budget_is_smaller_than_scheduled(self):
        from app.pipeline.collect.dread.adapter import INTERACTIVE_MAX_BODIES

        assert INTERACTIVE_MAX_BODIES < dread_scraper.DEFAULT_MAX_BODIES

    def test_api_path_uses_reduced_budget(self):
        """`pick_collector` ne sert que les chemins interactifs."""
        from app.pipeline.collect.routing import pick_collector
        from app.pipeline.collect.dread.adapter import INTERACTIVE_MAX_BODIES

        class _FakeSource:
            url = BASE

        collector = pick_collector(_FakeSource())
        assert isinstance(collector, DreadCollector)
        assert collector._max_bodies == INTERACTIVE_MAX_BODIES

    def test_scheduled_task_uses_full_budget(self):
        """La tache Celery instancie sans argument -> budget complet."""
        assert DreadCollector()._max_bodies == dread_scraper.DEFAULT_MAX_BODIES

    def test_budget_reaches_the_scraper(self, monkeypatch):
        seen = {}

        def _capture(url, subdreads, **kwargs):
            seen.update(kwargs)
            return []

        monkeypatch.setattr(
            "app.pipeline.collect.dread.adapter.fetch_dread_threads", _capture
        )
        DreadCollector(max_bodies=7).collect(_source())
        assert seen["max_bodies"] == 7


class TestDreadCollector:
    def test_builds_one_document_per_thread(self, monkeypatch):
        monkeypatch.setattr(
            "app.pipeline.collect.dread.adapter.fetch_dread_threads",
            lambda *_a, **_k: [
                DreadThread(
                    title="Restauration-exemple.fr - Database Leak",
                    thread_url=f"{BASE}post/abc123",
                    subdread="leaks",
                    author="seller99",
                    published_at=datetime(2025, 12, 27, tzinfo=timezone.utc),
                    comment_count=39,
                    body="120k rows from example-victim.sn",
                )
            ],
        )
        docs = DreadCollector().collect(_source())
        assert len(docs) == 1
        doc = docs[0]
        assert doc.collector == "dread"
        assert doc.title == "Restauration-exemple.fr - Database Leak"
        assert doc.author == "seller99"
        assert doc.published_at == datetime(2025, 12, 27, tzinfo=timezone.utc)
        assert "example-victim.sn" in doc.content
        assert doc.source_meta["subdread"] == "leaks"
        assert doc.source_meta["comment_count"] == 39

    def test_collect_failure_returns_empty(self, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("tor down")

        monkeypatch.setattr(
            "app.pipeline.collect.dread.adapter.fetch_dread_threads", _boom
        )
        assert DreadCollector().collect(_source()) == []

    def test_missing_body_is_flagged_not_dropped(self, monkeypatch):
        """Un fil dont le corps a echoue reste collecte : le titre porte deja
        du signal, et le lien permet la revue humaine."""
        monkeypatch.setattr(
            "app.pipeline.collect.dread.adapter.fetch_dread_threads",
            lambda *_a, **_k: [
                DreadThread(title="Sans corps", thread_url=f"{BASE}post/x", body=None)
            ],
        )
        docs = DreadCollector().collect(_source())
        assert len(docs) == 1
        assert "non recupere" in docs[0].content
