"""Verification TLS du collecteur DLS : coupee pour un `.onion` seulement.

Aucun reseau : `requests.get` et le delai de politesse sont remplaces."""

from __future__ import annotations

import pytest

from app.pipeline.collect.dls import fetch


@pytest.mark.parametrize(
    "url,attendu",
    [
        ("http://lockbit3753ekiocyo5epmpy6klmejchjtzddoekjlnt6.onion/", False),
        ("https://abc.onion/post/1", False),
        # Port et casse : `hostname` les normalise.
        ("http://ABC.ONION:8080/x", False),
        # Clearnet : la verification est la SEULE authentification du site.
        ("https://www.ransomlook.io/group/krybit", True),
        ("https://example.com/", True),
        # Pieges de sous-chaine : ce ne sont PAS des .onion.
        ("https://onion.example.com/", True),
        ("https://abc.onion.evil.com/", True),
        ("https://example.com/page.onion", True),
        # Illisible : dans le doute, on verifie.
        ("pas une url", True),
        ("", True),
    ],
)
def test_verification_coupee_pour_les_seuls_onion(url, attendu):
    assert fetch.verify_tls_for(url) is attendu


class _Reponse:
    status_code = 200
    text = "<html></html>"


@pytest.mark.parametrize(
    "url,attendu",
    [("http://abc.onion/", False), ("https://dls.example.com/", True)],
)
def test_requests_recoit_la_bonne_valeur(monkeypatch, url, attendu):
    """La regle ne sert a rien si elle n'atteint pas l'appel reseau."""
    vus = {}

    def faux_get(_url, **kwargs):
        vus.update(kwargs)
        return _Reponse()

    monkeypatch.setattr(fetch.requests, "get", faux_get)
    monkeypatch.setattr(fetch, "polite_delay", lambda: None)
    fetch.fetch_dls_html(url)
    assert vus["verify"] is attendu
