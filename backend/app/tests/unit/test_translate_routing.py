"""Choix du chemin de traduction (aucun modele reel charge).

Le module n'avait aucun test. On verifie ici QUEL CHEMIN est emprunte --
modele dedie, pivot par l'anglais, repli multilingue -- avec de faux modeles
qui marquent leur passage dans le texte."""

import pytest

from app.pipeline.enrich import translate as t


class _Faux:
    def __init__(self, nom: str):
        self.nom = nom

    def translate(self, text: str) -> str:
        return f"{text}>{self.nom}"


def _installes(monkeypatch, paires: set[str]) -> None:
    monkeypatch.setattr(
        t,
        "_load_pair",
        lambda s, c: _Faux(f"{s}-{c}") if f"{s}-{c}" in paires else None,
    )


def test_portugais_passe_par_le_multilingue_puis_le_francais(monkeypatch):
    """Le cas signale a l'usage : une annonce en portugais, aucune paire pt."""
    _installes(monkeypatch, {"ru-en", "en-fr", "mul-en"})
    assert t.translate_text("x", "pt", "fr") == "x>mul-en>en-fr"


def test_un_modele_dedie_prime_sur_le_multilingue(monkeypatch):
    """Le multilingue est un REPLI : sa qualite est moindre."""
    _installes(monkeypatch, {"ru-en", "en-fr", "mul-en"})
    assert t.translate_text("x", "ru", "fr") == "x>ru-en>en-fr"


def test_vers_l_anglais_s_arrete_au_pivot(monkeypatch):
    _installes(monkeypatch, {"en-fr", "mul-en"})
    assert t.translate_text("x", "pt", "en") == "x>mul-en"


def test_sans_modele_disponible_la_langue_est_refusee(monkeypatch):
    """Rien d'installe pour cette langue : on le DIT, on n'invente rien."""
    _installes(monkeypatch, {"ru-en", "en-fr"})
    with pytest.raises(t.TranslationUnavailableError):
        t.translate_text("x", "pt", "fr")


def test_meme_langue_rend_le_texte_intact(monkeypatch):
    _installes(monkeypatch, set())
    assert t.translate_text("x", "fr", "fr") == "x"
