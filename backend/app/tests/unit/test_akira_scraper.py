from app.pipeline.collect.akira.scraper import (
    _clean_wrapped_text,
    _extract_link,
    _max_page_from_pagination,
    _parse_leaks,
    is_akira_url,
)


class TestCleanWrappedText:
    def test_rejoins_word_split_mid_wrap(self):
        assert (
            _clean_wrapped_text("Exemple Distributin\ng Co\n")
            == "Exemple Distributing Co"
        )

    def test_keeps_existing_space_at_wrap_boundary(self):
        raw = "designed for rapid setting and stripping to meet the needs \nof competitive contractors."
        assert (
            _clean_wrapped_text(raw)
            == "designed for rapid setting and stripping to meet the needs of competitive contractors."
        )

    def test_preserves_paragraph_breaks(self):
        raw = "First paragraph.\n\nSecond paragraph."
        assert _clean_wrapped_text(raw) == "First paragraph.\n\nSecond paragraph."

    def test_strips_leading_trailing_whitespace(self):
        assert _clean_wrapped_text("\nHello\n") == "Hello"


class TestExtractLink:
    def test_extracts_url_from_jquery_terminal_markup(self):
        raw = "[[!;;;;https://3i7uisihrgv3v7kjafmhahhcmtjfepckhw5vournekuamhbt37liplid.onion/LEAKS_4/x.com/]download]"
        assert (
            _extract_link(raw)
            == "https://3i7uisihrgv3v7kjafmhahhcmtjfepckhw5vournekuamhbt37liplid.onion/LEAKS_4/x.com/"
        )

    def test_returns_none_when_no_match(self):
        assert _extract_link("") is None
        assert _extract_link("plain text, no markup") is None


class TestMaxPageFromPagination:
    def test_finds_highest_page_number(self):
        pagination = [
            "[[;#00ff00;;bg-green-dark;] 1 ]",
            "[[!;;;;#leaks?page=2&sort=date%3Adesc] 2 ]",
            "[[;#ffffff;;;] ... ]",
            "[[!;;;;#leaks?page=68&sort=date%3Adesc] 68 ]",
        ]
        assert _max_page_from_pagination(pagination) == 68

    def test_defaults_to_one_when_empty(self):
        assert _max_page_from_pagination([]) == 1


class TestParseLeaks:
    def test_parses_objects_into_leak_records(self):
        payload = {
            "objects": [
                {
                    "date": "2026-07-09",
                    "name": "Exemple Distributin\ng Co\n",
                    "desc": "Some desc\nhere.\n",
                    "url": "[[!;;;;https://example.onion/x/]download]",
                }
            ]
        }
        leaks = _parse_leaks(payload)
        assert len(leaks) == 1
        assert leaks[0].date == "2026-07-09"
        assert leaks[0].name == "Exemple Distributing Co"
        assert leaks[0].desc == "Some deschere."
        assert leaks[0].data_link == "https://example.onion/x/"

    def test_empty_objects_gives_empty_list(self):
        assert _parse_leaks({"objects": []}) == []
        assert _parse_leaks({}) == []


class TestIsAkiraUrl:
    def test_matches_known_hosts(self):
        assert is_akira_url(
            "https://akiral2iz6a7qgd3ayp3l6yub7xx2uep76idk3u2kollpj5z3z636bad.onion/"
        )
        assert is_akira_url(
            "https://akiralkzxzq2dsrzsrvbr2xgbbu2wgsmxryd4csgfameg52n7efvr2id.onion"
        )

    def test_rejects_unrelated_url(self):
        assert not is_akira_url("http://example.onion/")
