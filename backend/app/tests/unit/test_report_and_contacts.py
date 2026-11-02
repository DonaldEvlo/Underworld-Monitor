"""Rapport d'alerte et resolution des destinataires.

⚠️ Ces deux briques comblent le manque central du produit : le livrable est
« prevenir l'organisation », or aucune entite ne portait de contact et aucun
document ne pouvait sortir de l'outil.
"""

from datetime import date, datetime, timezone

import pytest

from app.pipeline.reporting.alert_report import (
    DocumentSource,
    DonneesRapport,
    ValeurDetectee,
    build_report_content,
)


def _donnees(**overrides) -> DonneesRapport:
    defauts = dict(
        sujet="Domaine Exemple (Afrique du Sud)",
        severite="critical",
        statut="open",
        date_alerte=date(2026, 9, 3),
        nombre_detections=4,
        corroboration="corroborated",
        gang="krybit",
        lien_preuve="https://www.ransomlook.io/screenshots/krybit/x.png",
        valeurs=[ValeurDetectee("domain", "domaine-exemple.co.za", 2)],
        documents=[
            DocumentSource(
                titre="www.domaine-exemple.co.za",
                source="KRYBIT (DLS)",
                collecteur="dls",
                url="http://krybit.onion/blog/abc",
                publie_le=datetime(2026, 9, 1, tzinfo=timezone.utc),
                collecte_le=datetime(2026, 9, 3, tzinfo=timezone.utc),
                extrait="STATUS PUBLISHED n VIEWS Domaine Exemple est un domaine sud-africain",
            )
        ],
    )
    defauts.update(overrides)
    return DonneesRapport(**defauts)


class TestLeRoleDuGroupeEstExplicite:
    """⚠️ ERREUR REELLE mesuree le 2026-09-04, corrigee : le modele avait ecrit
    « L'organisation Krybit a confirme cette exposition » -- l'ATTAQUANT
    presente comme un tiers de confiance, dans un document destine a la
    victime. Le vocabulaire du prompt est du code.
    """

    def test_le_gang_est_nomme_comme_attaquant(self):
        contenu = build_report_content(_donnees())
        assert "Groupe attaquant qui REVENDIQUE" in contenu
        assert "auteur présumé" in contenu

    def test_l_observateur_est_distingue_de_l_attaquant(self):
        contenu = build_report_content(_donnees())
        assert "tiers a l'attaquant" in contenu

    def test_les_extraits_sont_annonces_comme_contexte(self):
        """Les nombres des annonces (compteurs de vues) ne sont pas des faits :
        le modele en avait repris un comme volume de l'incident."""
        contenu = build_report_content(_donnees())
        assert "compteurs d'affichage, jamais des faits" in contenu


class TestVocabulaireDeCorroboration:
    """⚠️ Le statut technique ne doit jamais transiter tel quel : sur la
    synthese globale, `exclusive` avait fait ecrire au modele l'exact
    contraire de la verite."""

    def test_corrobore_dit_retrouvee_et_borne_ce_que_ca_prouve(self):
        """⚠️ REECRIT le 2026-09-26. Avant : « CONFIRMEE par un observateur
        independant ». Or l'agregateur lit le MEME site du groupe : il
        confirme que l'annonce existe, pas que la fuite est reelle. Le rapport
        va a la victime -- il ne doit pas suggerer une verification qui n'a
        pas eu lieu."""
        contenu = build_report_content(_donnees())
        assert "RETROUVÉE" in contenu
        assert "pas que la fuite est réelle" in contenu
        assert "independant" not in contenu

    def test_exclusive_n_est_pas_presente_comme_un_doute(self):
        contenu = build_report_content(_donnees(corroboration="exclusive", gang=None))
        assert "vue par nous seuls" in contenu
        assert "exclusive" not in contenu.lower()

    def test_absence_de_mesure_n_est_pas_un_resultat_negatif(self):
        contenu = build_report_content(_donnees(corroboration=None, gang=None))
        assert "jamais confrontée" in contenu


class TestBornesDuPrompt:
    def test_pas_de_valeur_brute_dans_les_faits(self):
        """Le rapport SORT de l'outil : il ne porte que des valeurs masquees."""
        contenu = build_report_content(
            _donnees(valeurs=[ValeurDetectee("email", "a***@exemple.test", 3)])
        )
        assert "a***@exemple.test" not in contenu  # les valeurs ne sont pas listees
        assert "email (3)" in contenu  # seuls les types et volumes le sont

    def test_le_prompt_interdit_le_markdown_et_l_invention(self):
        from app.pipeline.reporting.alert_report import REPORT_QUERY

        assert "markdown" in REPORT_QUERY.lower()
        assert "N'INVENTE AUCUN CHIFFRE" in REPORT_QUERY

    @pytest.mark.parametrize("sans", ["documents", "valeurs"])
    def test_donnees_partielles_ne_font_pas_echouer(self, sans):
        """Une alerte peu documentee doit produire un rapport, pas une erreur."""
        contenu = build_report_content(_donnees(**{sans: []}))
        assert "Organisation concernée" in contenu
