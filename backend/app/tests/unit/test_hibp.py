"""Tests de pipeline/enrich/hibp.py.

La regle critique verifiee ici est le **k-anonymity** : le mot de passe ne
doit jamais quitter le processus, seuls les 5 premiers caracteres de son
SHA-1 sont transmis (voir TestKAnonymity). C'est ce qui rend cette API
compatible avec CONTRIBUTING.md §2, contrairement a l'API Pwned Accounts."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.pipeline.enrich.hibp import (
    HibpLookupError,
    check_password,
    _parse_suffix_counts,
)

_PASSWORD = "azerty123"
_DIGEST = hashlib.sha1(_PASSWORD.encode()).hexdigest().upper()
_PREFIX, _SUFFIX = _DIGEST[:5], _DIGEST[5:]


def _response(body: str, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.text = body
    response.status_code = status
    response.raise_for_status = MagicMock()
    return response


class TestKAnonymity:
    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_only_the_five_char_prefix_is_transmitted(self, get):
        """Le coeur de la regle : ni le mot de passe, ni son hash complet ne
        doivent apparaitre dans la requete sortante."""
        get.return_value = _response(f"{_SUFFIX}:42")
        check_password(_PASSWORD)

        sent_url = get.call_args.args[0]
        assert sent_url.endswith(_PREFIX)
        assert _PASSWORD not in sent_url
        assert _SUFFIX not in sent_url
        assert _DIGEST not in sent_url

    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_result_never_carries_the_password_or_full_hash(self, get):
        get.return_value = _response(f"{_SUFFIX}:42")
        result = check_password(_PASSWORD)

        assert result.prefix == _PREFIX
        for value in vars(result).values():
            assert _PASSWORD != value
            assert _DIGEST != value

    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_padding_header_is_requested(self, get):
        """`Add-Padding` fait renvoyer du bruit par HIBP : anonymat renforce
        sans changer le resultat apres filtrage local."""
        get.return_value = _response(f"{_SUFFIX}:1")
        check_password(_PASSWORD)

        assert get.call_args.kwargs["headers"]["Add-Padding"] == "true"


class TestBreachCounting:
    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_known_password_returns_its_count(self, get):
        get.return_value = _response(f"AAAA:1\n{_SUFFIX}:35000\nBBBB:2")
        result = check_password(_PASSWORD)

        assert result.breach_count == 35000
        assert result.is_breached is True

    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_unknown_password_is_not_breached(self, get):
        """Suffixe absent de la reponse = jamais vu dans une fuite connue."""
        get.return_value = _response("AAAA:1\nBBBB:2")
        result = check_password(_PASSWORD)

        assert result.breach_count == 0
        assert result.is_breached is False

    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_matching_is_case_insensitive(self, get):
        get.return_value = _response(f"{_SUFFIX.lower()}:7")
        assert check_password(_PASSWORD).breach_count == 7

    def test_padding_lines_count_as_not_found(self):
        """Les lignes de padding ont un compte de 0 -- ne doivent jamais faire
        croire a une compromission."""
        assert _parse_suffix_counts(f"{_SUFFIX}:0", _SUFFIX) == 0


class TestErrorHandling:
    @patch("app.pipeline.enrich.hibp.requests.get")
    def test_network_failure_raises_lookup_error(self, get):
        get.side_effect = requests.ConnectionError("boom")
        with pytest.raises(HibpLookupError):
            check_password(_PASSWORD)

    def test_empty_password_is_rejected(self):
        with pytest.raises(HibpLookupError):
            check_password("")

    def test_non_numeric_count_raises(self):
        with pytest.raises(HibpLookupError):
            _parse_suffix_counts(f"{_SUFFIX}:pas-un-nombre", _SUFFIX)
