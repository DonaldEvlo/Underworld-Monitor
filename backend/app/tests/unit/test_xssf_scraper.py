from app.pipeline.collect.xssf.scraper import (
    _extract_inertia_payload,
    _parse_news_items,
    is_xssf_url,
)

SAMPLE_HTML = (
    '<html><body><div id="app" data-page="{&quot;component&quot;:&quot;News\\/Index&quot;,'
    "&quot;props&quot;:{&quot;news&quot;:{&quot;data&quot;:[{&quot;title&quot;:&quot;Test&quot;,"
    "&quot;excerpt&quot;:&quot;Excerpt&quot;,&quot;created_at&quot;:&quot;2026-07-01&quot;,"
    "&quot;section&quot;:{&quot;name&quot;:&quot;News&quot;},&quot;hack_group&quot;:null,"
    "&quot;attack_size&quot;:null,&quot;slug&quot;:&quot;test-abc&quot;}],"
    '&quot;meta&quot;:{&quot;current_page&quot;:1,&quot;last_page&quot;:9,&quot;total&quot;:126}}}}"></div></body></html>'
)


class TestExtractInertiaPayload:
    def test_extracts_and_decodes_json(self):
        payload = _extract_inertia_payload(SAMPLE_HTML)
        assert payload is not None
        assert payload["component"] == "News/Index"
        assert payload["props"]["news"]["meta"]["total"] == 126

    def test_returns_none_when_missing(self):
        assert (
            _extract_inertia_payload("<html><body>no payload here</body></html>")
            is None
        )


class TestParseNewsItems:
    def test_parses_items_with_section_and_optional_fields(self):
        payload = _extract_inertia_payload(SAMPLE_HTML)
        items = _parse_news_items(payload)
        assert len(items) == 1
        item = items[0]
        assert item.title == "Test"
        assert item.excerpt == "Excerpt"
        assert item.section == "News"
        assert item.hack_group is None
        assert item.slug == "test-abc"

    def test_empty_when_no_news_key(self):
        assert _parse_news_items({"props": {}}) == []

    def test_explicit_nulls_become_empty_strings(self):
        """Regression du 2026-08-21 : le JSON Inertia contient des `null`
        explicites. `obj.get("excerpt", "")` ne les rattrape PAS (il ne comble
        qu'une cle ABSENTE), donc un None se propageait jusqu'a
        `extract_mentioned_urls` et faisait echouer toute la source avec
        « expected string or bytes-like object, got 'NoneType' »."""
        payload = {
            "props": {
                "news": {
                    "data": [
                        {
                            "title": None,
                            "excerpt": None,
                            "created_at": None,
                            "slug": "x",
                        }
                    ]
                }
            }
        }
        item = _parse_news_items(payload)[0]
        assert item.title == ""
        assert item.excerpt == ""
        assert item.created_at == ""

    def test_missing_keys_still_default_to_empty(self):
        item = _parse_news_items({"props": {"news": {"data": [{}]}}})[0]
        assert item.title == ""
        assert item.excerpt == ""


class TestCollectorIsolatesBadItems:
    """Un item mal forme ne doit pas faire echouer toute la source.

    Avant correctif, le `try/except` de `collect()` n'entourait que le fetch :
    une exception dans la construction des documents echappait au collecteur
    et remontait telle quelle dans l'UI (message opaque, 0 document collecte)
    alors que les autres actualites etaient parfaitement exploitables."""

    def test_one_broken_item_does_not_lose_the_others(self, monkeypatch):
        import uuid
        from datetime import datetime, timezone

        from app.contracts.source import SourceContract, SourceType
        from app.pipeline.collect.xssf import adapter as xssf_adapter
        from app.pipeline.collect.xssf.adapter import XssfCollector
        from app.pipeline.collect.xssf.scraper import XssfNewsItem

        good = XssfNewsItem("T1", "Excerpt", "2026-08-21", None, None, None, "a")
        # `excerpt=None` reproduit exactement le cas rencontre en production.
        broken = XssfNewsItem("T2", None, "2026-08-21", None, None, None, "b")

        monkeypatch.setattr(
            xssf_adapter, "fetch_xssf_news", lambda _url: [good, broken, good]
        )
        source = SourceContract(
            id=uuid.uuid4(),
            name="XSSF",
            url="http://xssfnet2env65wnrlixkn4io3gzukirz7w767gdilk64iq6dg33jwsad.onion/",
            type=SourceType.FORUM,
            active=True,
            created_at=datetime.now(timezone.utc),
        )

        docs = XssfCollector().collect(source)

        assert len(docs) == 2
        assert all(d.collector == "xssf" for d in docs)


class TestIsXssfUrl:
    def test_matches_known_hosts(self):
        assert is_xssf_url(
            "http://xssfnet2env65wnrlixkn4io3gzukirz7w767gdilk64iq6dg33jwsad.onion/"
        )

    def test_rejects_unrelated_url(self):
        assert not is_xssf_url("http://example.onion/")
