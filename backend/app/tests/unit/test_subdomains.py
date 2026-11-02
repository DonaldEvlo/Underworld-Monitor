import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.pipeline.enrich.subdomains import SubdomainLookupError, find_subdomains


@pytest.fixture(autouse=True)
def _no_retry_delay():
    # Le retry (3 tentatives, backoff exponentiel, voir subdomains._fetch_crtsh
    # et _fetch_certspotter) est reel en production mais n'a pas a ralentir la
    # suite de tests -- seul le comportement (retry puis echec/succes) nous
    # interesse ici. _fetch_x.retry.sleep est l'attribut expose par tenacity
    # sur la fonction decoree elle-meme (plus fiable qu'un patch du module
    # tenacity interne).
    with (
        patch(
            "app.pipeline.enrich.subdomains._fetch_crtsh.retry.sleep", return_value=None
        ),
        patch(
            "app.pipeline.enrich.subdomains._fetch_certspotter.retry.sleep",
            return_value=None,
        ),
    ):
        yield


def _mock_response(payload=None, text_body=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    if text_body is not None:
        response.text = text_body
        response.json.side_effect = ValueError("no JSON")
    else:
        response.text = json.dumps(payload)
        response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        response.raise_for_status.return_value = None
    return response


class TestCrtShSuccess:
    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_extracts_unique_subdomains_from_name_value(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"name_value": "mail.example.test"},
                {"name_value": "vpn.example.test\nwww.example.test"},
                {"name_value": "mail.example.test"},  # doublon
            ]
        )
        result = find_subdomains("example.test")
        assert result == ["mail.example.test", "vpn.example.test", "www.example.test"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_excludes_the_queried_domain_itself(self, mock_get):
        mock_get.return_value = _mock_response(
            [{"name_value": "example.test\nmail.example.test"}]
        )
        result = find_subdomains("example.test")
        assert result == ["mail.example.test"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_strips_wildcard_prefix(self, mock_get):
        mock_get.return_value = _mock_response([{"name_value": "*.example.test"}])
        result = find_subdomains("example.test")
        assert result == []  # *.example.test normalise == example.test, exclu

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_wildcard_on_a_real_subdomain_is_kept_without_the_star(self, mock_get):
        mock_get.return_value = _mock_response([{"name_value": "*.mail.example.test"}])
        result = find_subdomains("example.test")
        assert result == ["mail.example.test"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_empty_body_returns_empty_list_not_an_error(self, mock_get):
        mock_get.return_value = _mock_response(text_body="")
        assert find_subdomains("example.test") == []

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_unrelated_domain_sharing_a_certificate_is_filtered_out(self, mock_get):
        # ex: un SAN multi-marques listant example.test ET example-other.test
        # -- example-other.test n'est pas un sous-domaine de example.test,
        # doit etre ecarte meme si crt.sh le renvoie dans le meme certificat.
        mock_get.return_value = _mock_response(
            [{"name_value": "mail.example.test\nexample-other.test"}]
        )
        result = find_subdomains("example.test")
        assert result == ["mail.example.test"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_domain_is_normalized_before_querying(self, mock_get):
        mock_get.return_value = _mock_response([])
        find_subdomains("  Example.TEST.  ")
        called_params = mock_get.call_args.kwargs["params"]
        assert called_params["q"] == "%.example.test"


class TestCertspotterFallback:
    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_falls_back_to_certspotter_when_crtsh_fails(self, mock_get):
        def side_effect(url, **kwargs):
            if "crt.sh" in url:
                return _mock_response(status_code=502)
            return _mock_response(
                [{"dns_names": ["mail.example.test", "vpn.example.test"]}]
            )

        mock_get.side_effect = side_effect
        result = find_subdomains("example.test")
        assert result == ["mail.example.test", "vpn.example.test"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_certspotter_filters_out_domains_sharing_a_san_without_being_subdomains(
        self, mock_get
    ):
        # cas reel constate : include_subdomains=true fait remonter des
        # domaines soeurs (operateur.cd, operateur-guinee.com) partageant un SAN
        # avec operateur.sn -- doivent etre ecartes, pas seulement le domaine
        # exact lui-meme.
        def side_effect(url, **kwargs):
            if "crt.sh" in url:
                return _mock_response(status_code=502)
            return _mock_response(
                [
                    {
                        "dns_names": [
                            "openid.operateur.sn",
                            "openid.operateur.cd",
                            "sso.operateur-guinee.com",
                        ]
                    }
                ]
            )

        mock_get.side_effect = side_effect
        result = find_subdomains("operateur.sn")
        assert result == ["openid.operateur.sn"]

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_both_sources_failing_raises_lookup_error(self, mock_get):
        mock_get.return_value = _mock_response(status_code=502)
        with pytest.raises(SubdomainLookupError):
            find_subdomains("example.test")

    @patch("app.pipeline.enrich.subdomains.requests.get")
    def test_network_failure_on_both_sources_raises_lookup_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        with pytest.raises(SubdomainLookupError):
            find_subdomains("example.test")
