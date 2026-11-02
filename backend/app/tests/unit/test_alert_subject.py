"""Libelle d'une alerte regionale : il doit nommer la victime."""

from app.pipeline.alerting.subject import region_alert_subject, region_alert_victim


def test_nomme_la_victime():
    assert (
        region_alert_subject(
            "Afrique", ["compagnie-aerienne.co.tz / compagnie-aerienne.com"]
        )
        == "compagnie-aerienne.co.tz / compagnie-aerienne.com — victime non déclarée (Afrique)"
    )


def test_plusieurs_victimes_comptees():
    assert region_alert_subject(
        "Afrique", ["Suivi Flotte Holdings", "Exemple"]
    ).startswith("Suivi Flotte Holdings +1 — ")


def test_sans_victime_nommee_repli_sur_la_region():
    assert (
        region_alert_subject("Afrique", ["", "  "]) == "Afrique — victime non déclarée"
    )


def test_nom_trop_long_tronque():
    assert len(region_alert_subject("Afrique", ["x" * 200]).split(" — ")[0]) == 60


def test_victime_seule_sans_le_suffixe_de_portee():
    """La liste affiche le NOM ; « non déclarée · Afrique » passe en badge."""
    assert (
        region_alert_victim(["Compagnie Aérienne Exemple"])
        == "Compagnie Aérienne Exemple"
    )
    assert region_alert_victim(["A", "B", "C"]) == "A +2"
    assert region_alert_victim(["", "  "]) is None
    # Le titre complet reste celui du dossier et du PDF.
    assert region_alert_subject("Afrique", ["Compagnie Aérienne Exemple"]) == (
        "Compagnie Aérienne Exemple — victime non déclarée (Afrique)"
    )
