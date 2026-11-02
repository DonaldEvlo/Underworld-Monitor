"""Exports CSV : injection de formule neutralisée (audit du 2026-10-06).

Les exports contiennent des titres et extraits publiés par des attaquants : une
cellule qui commence par « = », « + », « - », « @ », une tabulation ou un retour
chariot serait exécutée comme une formule à l'ouverture dans un tableur."""

from __future__ import annotations

import pytest

from app.api.routers.exports import _csv, cellule_sure


@pytest.mark.parametrize(
    "dangereuse",
    [
        '=HYPERLINK("http://exemple.invalid","Cliquez")',
        "+1+cmd|' /C calc'!A0",
        "-2+3",
        "@SUM(A1:A2)",
        "\t=1+1",
        "\r=1+1",
    ],
)
def test_une_formule_devient_du_texte(dangereuse):
    assert cellule_sure(dangereuse) == "'" + dangereuse


@pytest.mark.parametrize("sure", ["Acme Corp", "acme.com", "", "LockBit 3.0"])
def test_le_texte_ordinaire_est_intact(sure):
    assert cellule_sure(sure) == sure


def test_les_nombres_et_les_vides_passent_tels_quels():
    assert cellule_sure(-5) == -5
    assert cellule_sure(None) is None


def test_le_fichier_produit_est_neutralise():
    corps = _csv(["titre"], [['=HYPERLINK("x")'], ["Victime ordinaire"]], "t").body
    texte = corps.decode("utf-8")
    assert "'=HYPERLINK" in texte
    assert "\n=HYPERLINK" not in texte
    assert "Victime ordinaire" in texte
