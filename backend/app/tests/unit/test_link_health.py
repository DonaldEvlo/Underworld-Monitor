"""Tests de pipeline/enrich/link_health.py.

Aucun acces reseau reel : les reponses HTTP sont simulees. La regle critique
verifiee ici est qu'aucun corps de reponse n'est rapatrie au-dela du plafond
de lecture du titre (voir test_never_downloads_body_of_binary_content et
test_body_read_is_capped) -- c'est ce qui distingue une verification de
vivacite d'un telechargement de donnee fuitee (CONTRIBUTING.md §2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.pipeline.enrich.link_health import (
    LinkStatus,
    _MAX_TITLE_BYTES,
    check_link,
    check_links,
)


def _fake_response(
    status_code: int = 200,
    *,
    content_type: str | None = "text/html; charset=utf-8",
    body: bytes = b"",
    content_length: str | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    headers = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if content_length is not None:
        headers["Content-Length"] = content_length
    response.headers = headers

    def iter_content(chunk_size: int = 1024):
        for start in range(0, len(body), chunk_size):
            yield body[start : start + chunk_size]

    response.iter_content.side_effect = iter_content
    return response


def _session_returning(response) -> MagicMock:
    session = MagicMock()
    if isinstance(response, Exception):
        session.get.side_effect = response
    else:
        session.get.return_value = response
    return session


class TestStatusClassification:
    def test_200_is_alive(self):
        session = _session_returning(_fake_response(200))
        result = check_link("https://example.com/dump", session=session)
        assert result.status == LinkStatus.ALIVE
        assert result.http_status == 200

    @pytest.mark.parametrize("code", [404, 410])
    def test_404_and_410_are_gone(self, code):
        """Le signal le plus utile a l'analyste : l'annonce promettait un dump
        qui n'est plus la."""
        session = _session_returning(_fake_response(code))
        result = check_link("https://example.com/dump", session=session)
        assert result.status == LinkStatus.GONE

    @pytest.mark.parametrize("code", [401, 403])
    def test_401_and_403_are_restricted(self, code):
        """Un acces restreint est un resultat, jamais quelque chose a forcer
        (CONTRIBUTING.md §2.1) -- on ne reessaie pas, on ne s'authentifie pas."""
        session = _session_returning(_fake_response(code))
        result = check_link("https://example.com/dump", session=session)
        assert result.status == LinkStatus.RESTRICTED

    def test_500_is_server_error(self):
        session = _session_returning(_fake_response(503))
        result = check_link("https://example.com/", session=session)
        assert result.status == LinkStatus.SERVER_ERROR

    def test_network_failure_is_unreachable_and_never_raises(self):
        """Un lien mort est un cas de fonctionnement normal -- c'est meme ce
        qu'on cherche a mesurer -- pas une erreur applicative."""
        session = _session_returning(requests.ConnectionError("boom"))
        result = check_link("http://dead.onion/", session=session)
        assert result.status == LinkStatus.UNREACHABLE
        assert result.http_status is None


class TestSchemeAllowlist:
    """L'URL vient d'un document collecte (tiers hostile). Seuls http/https
    sont interroges ; le reste est ecarte AVANT toute requete -- la session
    ne doit meme pas etre touchee."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://127.0.0.1:5432/_",
            "ftp://postgres/",
            "http+unix://%2Fvar%2Frun%2Fdocker.sock/",
            "//example.com/dump",
        ],
    )
    def test_non_http_schemes_are_unreachable_without_a_request(self, url):
        session = MagicMock()
        result = check_link(url, session=session)
        assert result.status == LinkStatus.UNREACHABLE
        session.get.assert_not_called()

    def test_https_and_http_still_pass_through(self):
        for url in ("https://example.com/dump", "http://dead.onion/x"):
            session = _session_returning(_fake_response(200))
            assert check_link(url, session=session).status == LinkStatus.ALIVE
            session.get.assert_called_once()


class TestNoContentRapatriation:
    def test_never_downloads_body_of_binary_content(self):
        """Regle non negociable : sur un binaire (l'archive d'un dump), les
        en-tetes suffisent -- le corps ne doit jamais etre lu."""
        response = _fake_response(
            200,
            content_type="application/zip",
            body=b"PK\x03\x04leaked",
            content_length="9",
        )
        result = check_link(
            "https://files.example/dump.zip", session=_session_returning(response)
        )

        response.iter_content.assert_not_called()
        assert result.content_length == 9
        assert result.title is None

    def test_body_read_is_capped_for_html(self):
        """Meme sur du HTML, la lecture s'arrete au plafond : on qualifie une
        page, on ne l'archive pas. Verifie le nombre d'octets reellement
        consommes, pas la taille du corps disponible."""
        chunk_size = 1024
        body = b"<html><head>" + b"a" * (_MAX_TITLE_BYTES * 4)
        consumed = 0

        def counting_iter_content(chunk_size: int = 1024):
            nonlocal consumed
            for start in range(0, len(body), chunk_size):
                chunk = body[start : start + chunk_size]
                consumed += len(chunk)
                yield chunk

        response = _fake_response(200)
        response.iter_content.side_effect = counting_iter_content
        check_link("https://example.com/", session=_session_returning(response))

        assert consumed < len(body)
        assert consumed <= _MAX_TITLE_BYTES + chunk_size

    def test_result_carries_no_body_field(self):
        response = _fake_response(200, body=b"<html><title>Secret dump</title></html>")
        result = check_link(
            "https://example.com/", session=_session_returning(response)
        )
        assert not hasattr(result, "body")
        assert not hasattr(result, "content")

    def test_connection_is_released_without_consuming_body(self):
        response = _fake_response(
            200, content_type="application/octet-stream", body=b"x" * 100
        )
        check_link("https://example.com/f", session=_session_returning(response))
        response.close.assert_called_once()


class TestTitleExtraction:
    def test_extracts_and_normalizes_title(self):
        response = _fake_response(
            200, body=b"<html><head><title>  File\n  not   found </title></head>"
        )
        result = check_link(
            "https://example.com/", session=_session_returning(response)
        )
        assert result.title == "File not found"

    def test_missing_title_is_none(self):
        response = _fake_response(200, body=b"<html><body>no title here</body></html>")
        result = check_link(
            "https://example.com/", session=_session_returning(response)
        )
        assert result.title is None


class TestOnionHandling:
    def test_onion_is_flagged_and_tls_verification_disabled(self):
        """Un .onion s'authentifie par son adresse : le certificat auto-signe
        y est la norme. Voir onion_healthcheck.py, meme regle."""
        session = _session_returning(_fake_response(200))
        result = check_link("http://abcd.onion/thread", session=session)

        assert result.is_onion is True
        assert session.get.call_args.kwargs["verify"] is False

    def test_clearnet_keeps_tls_verification(self):
        session = _session_returning(_fake_response(200))
        result = check_link("https://example.com/", session=session)

        assert result.is_onion is False
        assert session.get.call_args.kwargs["verify"] is True


class TestCheckLinks:
    @patch("app.pipeline.enrich.link_health.polite_delay")
    @patch("app.pipeline.enrich.link_health._build_session")
    def test_deduplicates_by_host(self, build_session, polite_delay):
        """Un hebergeur cite dans 154 documents (constate sur le corpus reel)
        ne doit etre interroge qu'une fois : borne le trafic sortant et evite
        de marteler une source (CONTRIBUTING.md §2.3)."""
        build_session.return_value = _session_returning(_fake_response(200))
        results = check_links(
            [
                "https://t.me/chan/1",
                "https://t.me/chan/2",
                "https://other.example/x",
            ]
        )
        assert [r.host for r in results] == ["t.me", "other.example"]

    @patch("app.pipeline.enrich.link_health.polite_delay")
    @patch("app.pipeline.enrich.link_health._build_session")
    def test_polite_delay_between_hosts(self, build_session, polite_delay):
        build_session.return_value = _session_returning(_fake_response(200))
        check_links(["https://a.example/", "https://b.example/", "https://c.example/"])
        # Un delai entre les requetes, pas apres la derniere.
        assert polite_delay.call_count == 2

    @patch("app.pipeline.enrich.link_health._build_session")
    def test_ignores_urls_without_host(self, build_session):
        build_session.return_value = _session_returning(_fake_response(200))
        assert check_links(["not-a-url", ""]) == []
