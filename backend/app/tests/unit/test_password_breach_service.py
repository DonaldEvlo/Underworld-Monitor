"""Tests de services/password_breach_service.py.

Verifient l'agregation, le bornage, et surtout qu'aucun mot de passe en clair
ne sort de la fonction (TestNoPlaintextLeak) -- le service manipule
necessairement du clair en memoire, c'est le seul endroit du projet ou c'est
le cas, donc la frontiere doit etre verrouillee."""

from __future__ import annotations

from unittest.mock import patch

from app.pipeline.enrich.hibp import HibpLookupError, PasswordBreachResult
from app.services import password_breach_service
from app.services.password_breach_service import (
    PasswordBreachReport,
    check_corpus_passwords,
)


class _FakeQuery:
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


def _breached(count: int) -> PasswordBreachResult:
    return PasswordBreachResult(prefix="ABCDE", breach_count=count)


class TestExtraction:
    @patch.object(password_breach_service, "check_password", return_value=_breached(0))
    def test_counts_credentials_and_unique_passwords(self, check):
        db = _FakeSession(
            [
                ("alice@example.com:secret123 bob@example.com:secret123",),
                ("carol@example.com:autre456",),
            ]
        )
        report = check_corpus_passwords(db)

        assert report.credentials_found == 3
        # secret123 apparait deux fois -> un seul lookup
        assert report.unique_passwords == 2
        assert check.call_count == 2

    @patch.object(password_breach_service, "check_password", return_value=_breached(0))
    def test_handles_null_content(self, check):
        db = _FakeSession([(None,)])
        report = check_corpus_passwords(db)

        assert report.documents_scanned == 1
        assert report.credentials_found == 0

    @patch.object(password_breach_service, "check_password", return_value=_breached(0))
    def test_respects_lookup_cap(self, check):
        cap = password_breach_service._MAX_LOOKUPS_PER_RUN
        content = " ".join(f"u{i}@example.com:motdepasse{i}" for i in range(cap + 25))
        db = _FakeSession([(content,)])
        check_corpus_passwords(db)

        assert check.call_count == cap

    @patch.object(password_breach_service, "check_password", return_value=_breached(0))
    def test_limit_documents_applied(self, check):
        db = _FakeSession([("alice@example.com:secret123",)])
        check_corpus_passwords(db, limit_documents=10)

        assert db.query_obj.limit_applied == 10


class TestAggregation:
    @patch.object(password_breach_service, "check_password")
    def test_counts_breached_and_unknown(self, check):
        # Mots de passe >= 4 caracteres et tries : `check_corpus_passwords`
        # parcourt `sorted(unique_passwords)`, donc l'ordre de `side_effect`
        # suit l'ordre alphabetique, pas l'ordre d'apparition.
        check.side_effect = [_breached(50_000), _breached(0), _breached(5)]
        db = _FakeSession([("a@e.com:aaaa1 b@e.com:bbbb2 c@e.com:cccc3",)])
        report = check_corpus_passwords(db)

        assert report.passwords_checked == 3
        assert report.breached_count == 2
        assert report.unknown_count == 1

    @patch.object(password_breach_service, "check_password")
    def test_buckets_separate_recycling_from_targeted(self, check):
        """Un mot de passe vu 5 M de fois est du recyclage ; vu 3 fois, c'est
        un signal bien plus interessant."""
        check.side_effect = [_breached(5_000_000), _breached(3)]
        db = _FakeSession([("a@e.com:aaaa1 b@e.com:bbbb2",)])
        report = check_corpus_passwords(db)

        assert report.breach_buckets == {"100k+": 1, "1-10": 1}

    @patch.object(password_breach_service, "check_password")
    def test_lookup_errors_do_not_abort_the_pass(self, check):
        check.side_effect = [HibpLookupError("down"), _breached(10)]
        db = _FakeSession([("a@e.com:aaaa1 b@e.com:bbbb2",)])
        report = check_corpus_passwords(db)

        assert report.lookup_errors == 1
        assert report.passwords_checked == 1
        assert report.breached_count == 1

    def test_ratio_is_none_when_nothing_checked(self):
        report = PasswordBreachReport(
            documents_scanned=0,
            credentials_found=0,
            unique_passwords=0,
            passwords_checked=0,
            breached_count=0,
            unknown_count=0,
            lookup_errors=0,
            breach_buckets={},
        )
        assert report.breached_ratio is None


class TestNoPlaintextLeak:
    @patch.object(password_breach_service, "check_password", return_value=_breached(9))
    def test_report_contains_no_password(self, check):
        """Le rapport ne doit porter que des nombres -- aucun mot de passe, ni
        en clair ni hache."""
        db = _FakeSession([("alice@example.com:SuperSecret42",)])
        report = check_corpus_passwords(db)

        for value in vars(report).values():
            assert "SuperSecret42" != value
        assert "SuperSecret42" not in repr(report)

    @patch.object(password_breach_service, "check_password", return_value=_breached(9))
    def test_plaintext_is_not_logged(self, check, caplog):
        db = _FakeSession([("alice@example.com:SuperSecret42",)])
        with caplog.at_level("DEBUG"):
            check_corpus_passwords(db)

        assert "SuperSecret42" not in caplog.text
