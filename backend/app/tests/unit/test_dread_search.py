"""Tests de la recherche Dread (CONTRIBUTING.md §4).

Ce module n'avait AUCUN test alors que les autres collecteurs en ont — d'ou la
couverture ci-dessous, ecrite apres un test en conditions reelles le
2026-08-19 (Tor + site vivant, 20 resultats par mot-cle).

Aucun test ne touche le reseau : le fetch Playwright est toujours monkeypatche.
Le HTML utilise reproduit la structure reellement observee sur /search/."""

import pytest

from app.pipeline.collect.dread import search as dread_search
from app.pipeline.collect.dread.search import (
    _TransientFetchError,
    build_search_url,
    is_ddos_protection_page,
    parse_search_results,
    search_dread_for_keyword,
)

BASE = "http://dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion/"

# Deux structures coexistent sur la page de resultats : un fil trouve
# directement (.postTop > a.title) et un commentaire correspondant
# (.post-title > a). Le 3e item est volontairement malforme.
SEARCH_HTML = """
<div class="postBoard">
  <div class="item">
    <div class="postTop"><a class="title" href="/post/abc123">Fresh database dump 2026</a></div>
    <a href="/d/Leaks">/d/Leaks</a><a href="/u/seller99">seller99</a>
    <span title="2026-08-01 10:00">3 days ago</span>
    <div class="postContent">Contains emails and hashes</div>
  </div>
  <div class="item comment">
    <div class="post-title"><a href="/post/def456">Re: combo list</a></div>
    <a href="/d/Darknet">/d/Darknet</a><a href="/u/buyer">buyer</a>
    <span title="2026-08-02 11:00">2 days ago</span>
    <div class="comment-body">still working?</div>
  </div>
  <div class="item">aucun lien de titre, doit etre ignore</div>
</div>
"""


class TestBuildSearchUrl:
    def test_builds_internal_search_url(self):
        assert build_search_url(BASE, "leak") == f"{BASE}search/?q=leak"

    def test_encodes_spaces(self):
        assert build_search_url(BASE, "data leak").endswith("q=data%20leak")

    def test_encodes_accents_and_specials(self):
        """La watchlist contient des termes francais ; un encodage incorrect
        renverrait une recherche vide sans erreur."""
        url = build_search_url(BASE, "fuite données")
        assert "donn%C3%A9es" in url

    def test_ampersand_cannot_inject_extra_query_param(self):
        url = build_search_url(BASE, "a&b=c")
        assert url.endswith("q=a%26b%3Dc")


class TestAntiBotDetection:
    @pytest.mark.parametrize("marker", ["DDOS Protection", "ddos_form"])
    def test_detects_known_markers(self, marker):
        assert is_ddos_protection_page(f"<html><body>{marker}</body></html>") is True

    def test_normal_page_is_not_flagged(self):
        assert is_ddos_protection_page(SEARCH_HTML) is False


class TestParseSearchResults:
    def test_parses_both_item_structures(self):
        results = parse_search_results(SEARCH_HTML, BASE)
        assert [r["title"] for r in results] == [
            "Fresh database dump 2026",
            "Re: combo list",
        ]

    def test_ignores_items_without_title_link(self):
        """Un .item sans lien /post/ n'est pas un resultat exploitable."""
        assert len(parse_search_results(SEARCH_HTML, BASE)) == 2

    def test_links_are_absolute(self):
        results = parse_search_results(SEARCH_HTML, BASE)
        assert all(r["link"].startswith(BASE) for r in results)

    def test_extracts_metadata(self):
        first = parse_search_results(SEARCH_HTML, BASE)[0]
        assert first["subdread"] == "/d/Leaks"
        assert first["author"] == "seller99"
        assert first["date"] == "2026-08-01 10:00"
        assert first["snippet"] == "Contains emails and hashes"

    def test_missing_board_returns_empty(self):
        assert parse_search_results("<html><body>rien</body></html>", BASE) == []

    def test_empty_html_returns_empty(self):
        assert parse_search_results("", BASE) == []


class TestFetchRetriesOnTransientError:
    """Regression du correctif du 2026-08-19.

    `_fetch_search_html` renvoyait `None` quand le scraper repondait
    « Error: ... », ce qui rendait `@with_retry` inoperant (tenacity ne rejoue
    que sur exception). En recherche parallele, Playwright renvoie
    regulierement « page is navigating » : le mot-cle etait alors abandonne
    silencieusement et remontait 0 resultat alors que le site en avait 20."""

    @staticmethod
    def _patch_scraper(monkeypatch, scraper_output):
        """Neutralise reseau, delai et Playwright ; `scraper_output` est ce que
        renverrait `scraper.fetch_content` (liste de contenus)."""
        monkeypatch.setattr(dread_search, "polite_delay", lambda: None)
        monkeypatch.setattr(dread_search, "build_scraper_config", lambda **_: None)
        monkeypatch.setattr(
            dread_search, "build_socks5_proxy_url", lambda: "socks5://tor:9050"
        )

        class _FakeScraper:
            def __init__(self, _config):
                pass

            async def fetch_content(self, _url, proxy=None):
                return scraper_output

        monkeypatch.setattr(dread_search, "PlaywrightScraper", _FakeScraper)

    def test_scraper_error_raises_so_retry_can_fire(self, monkeypatch):
        self._patch_scraper(
            monkeypatch,
            [
                "Error: Failed to scrape the website.\n\nDetails: Page.content: "
                "Unable to retrieve content because the page is navigating"
            ],
        )
        # `.retry_with(stop=...)` coupe le backoff : on verifie que l'exception
        # est bien levee, pas la politique de reessai de tenacity elle-meme.
        with pytest.raises(_TransientFetchError):
            dread_search._fetch_search_html.retry_with(
                stop=lambda _s: True, reraise=True
            )(f"{BASE}search/?q=x")

    def test_empty_response_raises(self, monkeypatch):
        self._patch_scraper(monkeypatch, [])
        with pytest.raises(_TransientFetchError):
            dread_search._fetch_search_html.retry_with(
                stop=lambda _s: True, reraise=True
            )(f"{BASE}search/?q=x")

    def test_valid_html_is_returned_unchanged(self, monkeypatch):
        self._patch_scraper(monkeypatch, [SEARCH_HTML])
        assert dread_search._fetch_search_html(f"{BASE}search/?q=x") == SEARCH_HTML

    def test_retry_eventually_succeeds_after_transient_error(self, monkeypatch):
        """Le coeur du correctif : un echec transitoire suivi d'un succes doit
        remonter les resultats, la ou l'ancien code renvoyait None au 1er echec."""
        monkeypatch.setattr(dread_search, "polite_delay", lambda: None)
        monkeypatch.setattr(dread_search, "build_scraper_config", lambda **_: None)
        monkeypatch.setattr(
            dread_search, "build_socks5_proxy_url", lambda: "socks5://tor:9050"
        )
        calls = {"n": 0}

        class _FlakyScraper:
            def __init__(self, _config):
                pass

            async def fetch_content(self, _url, proxy=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    return ["Error: Failed to scrape the website."]
                return [SEARCH_HTML]

        monkeypatch.setattr(dread_search, "PlaywrightScraper", _FlakyScraper)

        assert dread_search._fetch_search_html(f"{BASE}search/?q=x") == SEARCH_HTML
        assert calls["n"] == 2


class TestSearchDreadForKeyword:
    """Contrat public : ne leve JAMAIS — un mot-cle en echec ne doit pas
    interrompre les 146 autres du lot."""

    def test_returns_parsed_hits(self, monkeypatch):
        monkeypatch.setattr(
            dread_search, "_fetch_search_html", lambda _url: SEARCH_HTML
        )
        assert len(search_dread_for_keyword(BASE, "dump")) == 2

    def test_anti_bot_page_returns_empty_without_raising(self, monkeypatch):
        monkeypatch.setattr(
            dread_search,
            "_fetch_search_html",
            lambda _url: "<html>DDOS Protection</html>",
        )
        assert search_dread_for_keyword(BASE, "dump") == []

    def test_fetch_failure_returns_empty_without_raising(self, monkeypatch):
        def _boom(_url):
            raise _TransientFetchError("indisponible apres retries")

        monkeypatch.setattr(dread_search, "_fetch_search_html", _boom)
        assert search_dread_for_keyword(BASE, "dump") == []

    def test_none_html_returns_empty(self, monkeypatch):
        monkeypatch.setattr(dread_search, "_fetch_search_html", lambda _url: None)
        assert search_dread_for_keyword(BASE, "dump") == []


class TestNoRawContentPersisted:
    """CONTRIBUTING.md regle 1 : Dread est une aide a la revue, pas une collecte.
    `search_dread_for_keyword` ne remonte que des metadonnees de fil (titre,
    lien, auteur, extrait) — jamais le corps d'un dump."""

    def test_result_keys_are_metadata_only(self, monkeypatch):
        monkeypatch.setattr(
            dread_search, "_fetch_search_html", lambda _url: SEARCH_HTML
        )
        hits = search_dread_for_keyword(BASE, "dump")
        assert set(hits[0]) == {
            "title",
            "link",
            "subdread",
            "author",
            "date",
            "snippet",
        }
