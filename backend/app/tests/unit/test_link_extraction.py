from app.pipeline.collect.link_extraction import (
    extract_mentioned_urls,
    is_content_locked,
)


class TestExtractMentionedUrls:
    def test_finds_a_single_url(self):
        text = "Check this out: http://leaksite1abcdefghijklmnopqrstuvwx.onion/data"
        assert extract_mentioned_urls(text) == [
            "http://leaksite1abcdefghijklmnopqrstuvwx.onion/data"
        ]

    def test_finds_multiple_distinct_urls_in_order(self):
        text = (
            "First https://a.onion/one then https://b.onion/two "
            "and also https://a.onion/one again"
        )
        assert extract_mentioned_urls(text) == [
            "https://a.onion/one",
            "https://b.onion/two",
        ]

    def test_strips_trailing_sentence_punctuation(self):
        text = "Link (https://a.onion/path), and also https://b.onion/other."
        assert extract_mentioned_urls(text) == [
            "https://a.onion/path",
            "https://b.onion/other",
        ]

    def test_excludes_the_document_own_url(self):
        own_url = "https://forum.onion/threads/123"
        text = (
            f"Voir le fil: {own_url} pour plus d'infos, sinon https://other.onion/leak"
        )
        result = extract_mentioned_urls(text, exclude_url=own_url)
        assert own_url not in result
        assert "https://other.onion/leak" in result

    def test_no_urls_returns_empty_list(self):
        assert extract_mentioned_urls("Aucun lien ici, juste du texte.") == []

    def test_deduplicates_repeated_urls(self):
        text = "https://a.onion/x https://a.onion/x https://a.onion/x"
        assert extract_mentioned_urls(text) == ["https://a.onion/x"]


class TestIsContentLocked:
    def test_detects_reply_and_react_wall(self):
        text = (
            'To see this hidden content, you need to "Reply & React" with one '
            "of the following reactions: Like, Love, Haha, Wow"
        )
        assert is_content_locked(text)

    def test_detects_case_insensitively(self):
        assert is_content_locked("TO SEE THIS HIDDEN CONTENT you must react")

    def test_normal_post_body_is_not_flagged(self):
        text = "Voici une fuite de donnees contenant 50000 comptes utilisateurs avec mots de passe."
        assert not is_content_locked(text)

    def test_empty_text_is_not_flagged(self):
        assert not is_content_locked("")
