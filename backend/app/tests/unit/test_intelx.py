from unittest.mock import MagicMock, patch

import pytest
import requests

from app.pipeline.enrich.intelx import IntelXLookupError, corroborate_domain


def _mock_response(payload=None, status_code=200, json_error=False):
    response = MagicMock()
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError("no JSON")
    else:
        response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        response.raise_for_status.return_value = None
    return response


class TestCorroborateDomain:
    @pytest.fixture(autouse=True)
    def _no_sleep_delay(self):
        # corroborate_domain() attend 1s avant de lire les resultats (voir
        # intelx.py) -- reel en production, inutile de ralentir la suite.
        with patch("app.pipeline.enrich.intelx.time.sleep", return_value=None):
            yield

    def test_missing_api_key_raises_without_any_request(self):
        with pytest.raises(IntelXLookupError):
            corroborate_domain("example.test", "")

    def test_empty_domain_raises(self):
        with pytest.raises(IntelXLookupError):
            corroborate_domain("   ", "fake-key")

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_counts_hits_per_bucket_with_a_single_result_call(
        self, mock_post, mock_get
    ):
        mock_post.return_value = _mock_response({"id": "search-123"})
        mock_get.return_value = _mock_response(
            {
                "status": 1,
                "records": [
                    {"bucket": "leaks.public"},
                    {"bucket": "leaks.public"},
                    {"bucket": "pastes"},
                ],
            }
        )

        result = corroborate_domain("Example.TEST.", "fake-key")

        assert result.term == "example.test"
        assert result.hit_count == 3
        assert result.buckets == {"leaks.public": 2, "pastes": 1}
        # Un seul GET pour les resultats + un GET pour terminate -- jamais de
        # boucle de polling (quota tres serre sur ce tier, voir intelx.py).
        assert mock_get.call_count == 2

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_null_records_is_treated_as_empty_not_a_crash(self, mock_post, mock_get):
        # Constate en usage reel : IntelX peut renvoyer records=null (pas
        # juste absent) si la recherche n'est pas encore initialisee cote
        # serveur au moment de la lecture -- ne doit jamais crasher.
        mock_post.return_value = _mock_response({"id": "search-123"})
        mock_get.return_value = _mock_response({"status": 0, "records": None})

        result = corroborate_domain("example.test", "fake-key")

        assert result.hit_count == 0
        assert result.buckets == {}

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_sends_api_key_in_x_key_header(self, mock_post, mock_get):
        mock_post.return_value = _mock_response({"id": "search-123"})
        mock_get.return_value = _mock_response({"status": 1, "records": []})

        corroborate_domain("example.test", "fake-key")

        assert mock_post.call_args.kwargs["headers"]["x-key"] == "fake-key"
        assert mock_get.call_args_list[0].kwargs["headers"]["x-key"] == "fake-key"

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_calls_terminate_to_free_the_concurrent_search_slot(
        self, mock_post, mock_get
    ):
        mock_post.return_value = _mock_response({"id": "search-123"})
        mock_get.return_value = _mock_response({"status": 1, "records": []})

        corroborate_domain("example.test", "fake-key")

        terminate_call = mock_get.call_args_list[-1]
        assert "search/terminate" in terminate_call.args[0]
        assert terminate_call.kwargs["params"]["id"] == "search-123"

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_terminate_failure_does_not_break_the_result(self, mock_post, mock_get):
        mock_post.return_value = _mock_response({"id": "search-123"})

        def get_side_effect(url, **kwargs):
            if "terminate" in url:
                raise requests.ConnectionError("terminate unreachable")
            return _mock_response({"status": 1, "records": [{"bucket": "pastes"}]})

        mock_get.side_effect = get_side_effect

        result = corroborate_domain("example.test", "fake-key")
        assert result.hit_count == 1

    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_401_on_search_raises_lookup_error(self, mock_post):
        mock_post.return_value = _mock_response(status_code=401)
        with pytest.raises(IntelXLookupError):
            corroborate_domain("example.test", "bad-key")

    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_unparsable_search_response_raises_lookup_error(self, mock_post):
        mock_post.return_value = _mock_response(json_error=True)
        with pytest.raises(IntelXLookupError):
            corroborate_domain("example.test", "fake-key")

    @patch("app.pipeline.enrich.intelx.requests.get")
    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_unparsable_result_response_raises_lookup_error(self, mock_post, mock_get):
        mock_post.return_value = _mock_response({"id": "search-123"})
        mock_get.return_value = _mock_response(json_error=True)
        with pytest.raises(IntelXLookupError):
            corroborate_domain("example.test", "fake-key")

    @patch("app.pipeline.enrich.intelx.requests.post")
    def test_network_failure_on_search_raises_lookup_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("boom")
        with pytest.raises(IntelXLookupError):
            corroborate_domain("example.test", "fake-key")


class TestHitCountIsSaturated:
    """⚠️ `hit_count` n'est PAS une mesure d'ampleur.

    Mesure du 2026-08-26 sur l'API reelle : `google.com` rend 200 et
    `institution-exemple.sn` (petite institution senegalaise) rend 200 aussi --
    c'est notre propre plafond `_MAX_RESULTS`, pas un comptage. Seul le
    caractere NON NUL porte de l'information (un domaine inexistant rend 0).

    Ces tests verrouillent le drapeau qui empeche l'interface de presenter un
    plafond comme une gravite."""

    def test_flags_truncation_at_ceiling(self):
        from app.pipeline.enrich.intelx import _MAX_RESULTS, IntelXCorroborationResult

        result = IntelXCorroborationResult("acme.com", _MAX_RESULTS, {})
        assert result.is_truncated is True

    def test_partial_result_is_not_truncated(self):
        from app.pipeline.enrich.intelx import IntelXCorroborationResult

        assert IntelXCorroborationResult("acme.com", 12, {}).is_truncated is False

    def test_zero_hits_is_meaningful_and_not_truncated(self):
        """0 est le seul verdict quantitatif fiable : le domaine n'apparait
        dans aucun index IntelX."""
        from app.pipeline.enrich.intelx import IntelXCorroborationResult

        assert IntelXCorroborationResult("inexistant.sn", 0, {}).is_truncated is False
