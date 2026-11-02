from app.pipeline.collect.ransomlook.scraper import (
    _parse_discovered,
    _parse_posts,
    is_ransomlook_url,
)


class TestParsePosts:
    def test_parses_valid_entries(self):
        payload = [
            {
                "group_name": "qilin",
                "post_title": "Acme Corp",
                "discovered": "2026-07-12T16:00:54.072484Z",
            },
            {
                "group_name": "akira",
                "post_title": "Example Inc",
                "discovered": "2026-07-12T16:02:08.123869Z",
            },
        ]
        posts = _parse_posts(payload)
        assert len(posts) == 2
        assert posts[0].group_name == "qilin"
        assert posts[0].post_title == "Acme Corp"

    def test_skips_entries_missing_required_fields(self):
        payload = [
            {"group_name": "qilin", "post_title": "Acme Corp", "discovered": None},
            {
                "group_name": "",
                "post_title": "Missing group",
                "discovered": "2026-07-12T16:00:54Z",
            },
            {
                "group_name": "akira",
                "post_title": "",
                "discovered": "2026-07-12T16:00:54Z",
            },
        ]
        assert _parse_posts(payload) == []

    def test_empty_payload_returns_empty_list(self):
        assert _parse_posts([]) == []

    def test_parses_wrapped_object_payload(self):
        """L'API retourne desormais {"posts": [...]} au lieu d'un tableau nu
        (constate en usage reel : le collecteur levait AttributeError en
        iterant sur les cles du dict, et ne produisait donc aucun document)."""
        payload = {
            "posts": [
                {
                    "group_name": "akira",
                    "post_title": "Exemple Construction",
                    "discovered": "2026-07-15T15:53:44.997825Z",
                }
            ]
        }
        posts = _parse_posts(payload)
        assert len(posts) == 1
        assert posts[0].group_name == "akira"
        assert posts[0].post_title == "Exemple Construction"

    def test_wrapped_payload_without_posts_key_returns_empty_list(self):
        assert _parse_posts({}) == []
        assert _parse_posts({"posts": None}) == []

    def test_non_dict_entries_are_skipped(self):
        assert _parse_posts(["unexpected string", 42]) == []


class TestParseDiscovered:
    def test_parses_iso_with_z_suffix(self):
        result = _parse_discovered("2026-07-12T16:00:54.072484Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 7

    def test_invalid_value_returns_none(self):
        assert _parse_discovered("not-a-date") is None
        assert _parse_discovered(None) is None


class TestIsRansomlookUrl:
    def test_matches_ransomlook_host(self):
        assert is_ransomlook_url("https://www.ransomlook.io/api/posts")

    def test_rejects_unrelated_url(self):
        assert not is_ransomlook_url("https://example.com/api/posts")
