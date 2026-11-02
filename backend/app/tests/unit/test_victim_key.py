"""Cle de victime des alertes regionales (une alerte par victime, 0032).

Seule definition, partagee par la generation et la scission : ces tests la
verrouillent pour les deux."""

from __future__ import annotations

from app.pipeline.alerting.matching import victim_key


class TestCleDeVictime:
    def test_www_et_casse_rabattus(self):
        assert victim_key("WWW.Suivi-Flotte.co.za.") == "suivi-flotte.co.za"

    def test_une_adresse_designe_son_organisation(self):
        """Simulation du 2026-09-30 : `c***@quartier-exemple.co.za` et `quartier-exemple.co.za`
        comptaient pour deux victimes, donc deux alertes."""
        assert victim_key("c***@quartier-exemple.co.za") == "quartier-exemple.co.za"

    def test_le_domaine_declare_l_emporte_sur_la_raison_sociale(self):
        assert (
            victim_key("Exemple Defence Force", "www.defense-exemple.gov.na")
            == "defense-exemple.gov.na"
        )

    def test_sans_domaine_la_raison_sociale(self):
        assert (
            victim_key("EXEMPLE Unlimited Architects") == "exemple unlimited architects"
        )

    def test_vide(self):
        assert victim_key(None) == ""
