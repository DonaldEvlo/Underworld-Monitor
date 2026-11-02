from app.core.url_utils import normalize_url
from app.pipeline.collect.github_import import find_new_candidates

SAMPLE_MD = """|Name|Status|Description|
| ------ | ------ | ------ |
|[Already Known](http://known1abcdefghijklmnopqrstuvwxyz234567.onion)| ONLINE|
|[Known Trailing Slash](http://known2abcdefghijklmnopqrstuvwxyz234567.onion/)| ONLINE|
|[Brand New](http://newone1abcdefghijklmnopqrstuvwxyz234567.onion)| ONLINE|
|[Also New](https://newtwo1abcdefghijklmnopqrstuvwxyz234567.onion/)| ONLINE|
|[Not Onion](https://example.com)| ONLINE|
"""


class TestFindNewCandidates:
    def test_excludes_already_known_urls_regardless_of_scheme_or_slash(self):
        existing = {
            normalize_url("https://known1abcdefghijklmnopqrstuvwxyz234567.onion/")
        }
        candidates = find_new_candidates(SAMPLE_MD, existing, normalize_url)
        names = [name for name, _ in candidates]
        assert "Already Known" not in names

    def test_keeps_genuinely_new_onion_entries(self):
        candidates = find_new_candidates(SAMPLE_MD, set(), normalize_url)
        names = {name for name, _ in candidates}
        assert "Brand New" in names
        assert "Also New" in names

    def test_ignores_non_onion_entries(self):
        candidates = find_new_candidates(SAMPLE_MD, set(), normalize_url)
        names = {name for name, _ in candidates}
        assert "Not Onion" not in names

    def test_empty_existing_set_keeps_everything_onion(self):
        candidates = find_new_candidates(SAMPLE_MD, set(), normalize_url)
        assert len(candidates) == 4  # tout sauf "Not Onion"


class TestFetchAllLists:
    """Perimetre d'import : `forum.md` UNIQUEMENT (decision du 2026-08-22).

    Le depot deepdarkCTI contient d'autres listes exploitables
    (`ransomware_gang.md` = 583 adresses inconnues a lui seul), mais elles sont
    hors perimetre retenu. Ces tests verrouillent le choix pour qu'un ajout
    soit un acte delibere, pas un effet de bord."""

    def test_imports_forum_md(self):
        from app.pipeline.collect.github_import import (
            DEFAULT_FORUM_MD_URL,
            IMPORTED_LIST_URLS,
        )

        assert DEFAULT_FORUM_MD_URL in IMPORTED_LIST_URLS

    def test_imports_only_forum_md(self):
        """Perimetre volontairement restreint aux forums."""
        from app.pipeline.collect.github_import import IMPORTED_LIST_URLS

        assert IMPORTED_LIST_URLS == (
            "https://raw.githubusercontent.com/fastfire/deepdarkCTI/main/forum.md",
        )

    def test_no_other_deepdarkcti_list_is_imported(self):
        from app.pipeline.collect.github_import import IMPORTED_LIST_URLS

        joined = " ".join(IMPORTED_LIST_URLS)
        for other in (
            "ransomware_gang.md",
            "markets.md",
            "search_engines.md",
            "counterfeit_goods",
            "rat.md",
            "malware_samples",
        ):
            assert other not in joined

    def test_concatenates_every_list(self, monkeypatch):
        from app.pipeline.collect import github_import

        monkeypatch.setattr(github_import, "fetch_forum_md", lambda url: f"<{url}>")
        text = github_import.fetch_all_lists(("http://a", "http://b"))
        assert text == "<http://a>\n<http://b>"

    def test_one_failing_list_does_not_break_the_others(self, monkeypatch):
        """Perdre une liste ne doit pas faire echouer l'import des autres."""
        from app.pipeline.collect import github_import

        def _flaky(url):
            if url.endswith("bad"):
                raise RuntimeError("404")
            return f"<{url}>"

        monkeypatch.setattr(github_import, "fetch_forum_md", _flaky)
        text = github_import.fetch_all_lists(("http://ok", "http://bad"))
        assert text == "<http://ok>"

    def test_duplicate_url_across_lists_is_deduplicated(self):
        """Une adresse presente dans deux listes ne doit produire qu'un
        candidat (dedup par URL dans parse_onion_entries_from_text)."""
        from app.pipeline.collect.github_import import find_new_candidates

        dup = (
            "|Name|Status|\n| ------ | ------ |\n"
            "|[Dup](http://dupe111abcdefghijklmnopqrstuvwxyz234567.onion)| ONLINE|\n"
        )
        candidates = find_new_candidates(dup + dup, set(), normalize_url)
        assert len(candidates) == 1


class TestRealWorldRowFormats:
    r"""Regression du 2026-08-22 : le depot amont a change le formatage de ses
    tableaux markdown (`| [Nom](url)` avec une espace apres le pipe), alors que
    `_ROW_RE` exigeait `^\|\[` colle.

    Consequence : le parser renvoyait **0 entree** sur le fichier reel. L'import
    GitHub annoncait donc « 0 nouvelle adresse » -- indiscernable d'un depot a
    jour, alors que 762 adresses inconnues attendaient. Un echec silencieux,
    pas une erreur."""

    def test_parses_row_with_space_after_pipe(self):
        from app.pipeline.collect.onion_healthcheck import (
            parse_onion_entries_from_text,
        )

        line = "| [BREACH FORUMS](http://breach5yz2b5lepmq4gaqwcon3jippw3bislhvv.onion) | ONLINE |"
        entries = parse_onion_entries_from_text(line)
        assert len(entries) == 1
        assert entries[0][0] == "BREACH FORUMS"

    def test_still_parses_legacy_tight_format(self):
        """L'ancien format sans espace doit continuer de marcher."""
        from app.pipeline.collect.onion_healthcheck import (
            parse_onion_entries_from_text,
        )

        line = (
            "|[Legacy](http://legacy1abcdefghijklmnopqrstuvwxyz234567.onion)| ONLINE|"
        )
        assert len(parse_onion_entries_from_text(line)) == 1

    def test_clearnet_row_is_still_excluded(self):
        """`bf.st` (BREACH FORUMS clearnet, ajoute le 2026-08-17) repond 403
        derriere Cloudflare depuis Tor : le collecter exigerait de contourner
        une protection anti-bot, ce que la regle 1 interdit."""
        from app.pipeline.collect.onion_healthcheck import (
            parse_onion_entries_from_text,
        )

        assert (
            parse_onion_entries_from_text("| [BREACH FORUMS](https://bf.st) | ONLINE |")
            == []
        )

    def test_url_with_surrounding_spaces_is_trimmed(self):
        from app.pipeline.collect.onion_healthcheck import (
            parse_onion_entries_from_text,
        )

        line = "| [Spaced]( http://spaced1abcdefghijklmnopqrstuvwxyz234567.onion ) | ONLINE |"
        entries = parse_onion_entries_from_text(line)
        assert len(entries) == 1
        assert entries[0][1].endswith(".onion")
