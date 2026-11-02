"""Tests de services/link_health_service.py -- agregation et bornage.

Le reseau est entierement simule (check_links est patche) : ces tests portent
sur la selection des documents, la deduplication par hote et les comptages,
pas sur le comportement HTTP (couvert par test_link_health.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from app.pipeline.enrich.link_health import LinkHealthResult, LinkStatus
from app.services import link_health_service
from app.services.link_health_service import LinkHealthReport, check_corpus_links


class _FakeQuery:
    """Imite la chaine query(...).filter(...).order_by(...).limit(...).all()
    utilisee par _collect_urls, en enregistrant ce qui a ete demande."""

    def __init__(self, rows):
        self._rows = rows
        self.limit_applied = None

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, value):
        self.limit_applied = value
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.query_obj = _FakeQuery(rows)

    def query(self, *_args):
        return self.query_obj


def _result(host: str, status: LinkStatus = LinkStatus.ALIVE) -> LinkHealthResult:
    return LinkHealthResult(
        url=f"https://{host}/x",
        host=host,
        is_onion=host.endswith(".onion"),
        status=status,
        http_status=200 if status == LinkStatus.ALIVE else 404,
        title=None,
        content_type=None,
        content_length=None,
        checked_at=datetime.now(timezone.utc),
    )


class TestUrlCollection:
    @patch.object(link_health_service, "check_links", return_value=[])
    def test_counts_documents_with_and_without_links(self, check_links):
        db = _FakeSession(
            [
                ("https://src/1", "voir https://a.example/dump"),
                ("https://src/2", "aucun lien ici"),
                ("https://src/3", "https://b.example/x et https://c.example/y"),
            ]
        )
        report = check_corpus_links(db)

        assert report.documents_scanned == 3
        assert report.documents_with_links == 2

    @patch.object(link_health_service, "check_links", return_value=[])
    def test_excludes_the_document_own_url(self, check_links):
        """Une source ne doit pas se lister elle-meme comme lien mentionne --
        comportement herite de link_extraction.extract_mentioned_urls."""
        db = _FakeSession(
            [("https://src/1", "voir https://src/1 et https://a.example/")]
        )
        check_corpus_links(db)

        checked = check_links.call_args.args[0]
        assert "https://src/1" not in checked

    @patch.object(link_health_service, "check_links", return_value=[])
    def test_deduplicates_by_host_before_capping(self, check_links):
        """La dedup precede le plafond : sinon on verifierait N fois le meme
        hebergeur au lieu de N hotes distincts."""
        content = " ".join(f"https://same.example/{i}" for i in range(50))
        db = _FakeSession([("https://src/1", content + " https://other.example/z")])
        check_corpus_links(db)

        checked = check_links.call_args.args[0]
        assert len(checked) == 2

    @patch.object(link_health_service, "check_links", return_value=[])
    def test_respects_max_hosts_per_run(self, check_links):
        content = " ".join(
            f"https://h{i}.example/"
            for i in range(link_health_service._MAX_HOSTS_PER_RUN + 40)
        )
        db = _FakeSession([("https://src/1", content)])
        check_corpus_links(db)

        checked = check_links.call_args.args[0]
        assert len(checked) == link_health_service._MAX_HOSTS_PER_RUN

    @patch.object(link_health_service, "check_links", return_value=[])
    def test_limit_documents_is_applied_to_the_query(self, check_links):
        db = _FakeSession([("https://src/1", "https://a.example/")])
        check_corpus_links(db, limit_documents=25)

        assert db.query_obj.limit_applied == 25

    @patch.object(link_health_service, "check_links", return_value=[])
    def test_handles_documents_with_null_content(self, check_links):
        db = _FakeSession([("https://src/1", None)])
        report = check_corpus_links(db)

        assert report.documents_scanned == 1
        assert report.documents_with_links == 0


class TestAggregation:
    @patch.object(link_health_service, "check_links")
    def test_counts_by_status(self, check_links):
        check_links.return_value = [
            _result("a.example", LinkStatus.ALIVE),
            _result("b.example", LinkStatus.GONE),
            _result("c.example", LinkStatus.GONE),
            _result("d.onion", LinkStatus.UNREACHABLE),
        ]
        db = _FakeSession([("https://src/1", "https://a.example/")])
        report = check_corpus_links(db)

        assert report.counts_by_status == {"alive": 1, "gone": 2, "unreachable": 1}
        assert report.hosts_checked == 4

    @patch.object(link_health_service, "check_links")
    def test_alive_ratio(self, check_links):
        check_links.return_value = [
            _result("a.example", LinkStatus.ALIVE),
            _result("b.example", LinkStatus.GONE),
        ]
        db = _FakeSession([("https://src/1", "https://a.example/")])
        report = check_corpus_links(db)

        assert report.alive_ratio == 0.5

    def test_alive_ratio_is_none_when_nothing_checked(self):
        """ "Aucune mesure" n'est pas "tout est mort" -- un ratio de 0.0 ferait
        croire a un corpus entierement casse."""
        report = LinkHealthReport(
            results=[],
            documents_scanned=0,
            documents_with_links=0,
            hosts_checked=0,
            counts_by_status={},
        )
        assert report.alive_ratio is None
