"""Nom de fichier du rapport PDF : accents translitteres, jamais avales."""

from app.pipeline.reporting.nommage import nom_de_fichier


def test_les_accents_sont_translitteres() -> None:
    sujet = "compagnie-aerienne.co.tz — victime non déclarée (Afrique)"
    assert (
        nom_de_fichier(sujet) == "compagnie-aerienne-co-tz-victime-non-declaree-afrique"
    )


def test_sujet_vide_ou_sans_lettre() -> None:
    assert nom_de_fichier("") == "alerte"
    assert nom_de_fichier("— —") == "alerte"
