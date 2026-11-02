"""Tests du niveau de credibilite (plan de credibilite, phase 5).

Logique pure. Un test temoin par niveau prouve qu'il est ATTEIGNABLE : sur le
corpus actuel, `doubtful` ne peut pas l'etre (son unique entree, le lien de
dump mort, n'a pas de matiere mesuree), et aucune mesure en base ne le
montrerait."""

from __future__ import annotations

import pytest

from app.pipeline.alerting.credibility import (
    Credibility,
    CredibilityInput,
    assess,
)
from app.pipeline.reporting.alert_report import (
    LIBELLES_CREDIBILITE,
    libelle_credibilite,
)


def _niveau(**faits):
    return assess(CredibilityInput(has_documents=True, **faits)).level


class TestChaqueNiveauEstAtteignable:
    def test_confirmed(self):
        assert _niveau(press_confirmed=True) is Credibility.CONFIRMED

    def test_doubtful_par_lien_mort(self):
        assert _niveau(download_link_gone=True) is Credibility.DOUBTFUL

    def test_published(self):
        assert _niveau(publication_status="published") is Credibility.PUBLISHED

    def test_claimed_en_attente(self):
        resultat = assess(
            CredibilityInput(
                has_documents=True,
                publication_status="pending",
                publication_evidence="marquée « unpublished »",
                publication_source="BEAST",
            )
        )
        assert resultat.level is Credibility.CLAIMED
        assert "menace" in resultat.evidence and "BEAST" in resultat.evidence

    def test_claimed_forum(self):
        resultat = assess(CredibilityInput(has_documents=True))
        assert resultat.level is Credibility.CLAIMED
        assert "forum" in resultat.evidence

    def test_claimed_site_de_fuite_sans_statut(self):
        resultat = assess(CredibilityInput(has_documents=True, from_victim_site=True))
        assert resultat.level is Credibility.CLAIMED
        assert "non exposé" in resultat.evidence

    def test_not_evaluated(self):
        assert (
            assess(CredibilityInput(has_documents=False)).level
            is Credibility.NOT_EVALUATED
        )


class TestOrdreDeDecision:
    def test_la_presse_l_emporte_sur_tout_doute(self):
        """Une source exterieure au gang n'est pas dementie par un lien mort :
        le gang a pu retirer ses donnees apres coup."""
        assert (
            _niveau(press_confirmed=True, download_link_gone=True)
            is Credibility.CONFIRMED
        )

    def test_le_doute_l_emporte_sur_la_publication_declaree(self):
        assert (
            _niveau(publication_status="published", download_link_gone=True)
            is Credibility.DOUBTFUL
        )

    @pytest.mark.parametrize("valeur", [None, False])
    def test_non_mesure_n_est_jamais_un_doute(self, valeur):
        """None = pas mesure (phase 3 sans matiere sur ce corpus), jamais
        « douteux »."""
        assert (
            _niveau(publication_status="published", download_link_gone=valeur)
            is Credibility.PUBLISHED
        )


class TestQualificatifsDeRevendication:
    """Phase 4, revue le 2026-09-30 : une victime publiee par plusieurs gangs
    n'est PAS une fuite douteuse (voir claim_history.py). Le qualificatif
    decrit ; il ne change jamais le niveau."""

    REPUBLICATION = (("transitaire-exemple.com", "lockbit3", "2023-09-16"),)
    DISPUTE = (("victime.co.za", ("beast", "qilin")),)

    def test_une_republication_ne_rend_pas_douteuse(self):
        resultat = assess(
            CredibilityInput(
                has_documents=True,
                publication_status="published",
                republications=self.REPUBLICATION,
            )
        )
        assert resultat.level is Credibility.PUBLISHED
        assert (
            "republication : transitaire-exemple.com déjà revendiquée par lockbit3 "
            "le 2023-09-16" in resultat.evidence
        )

    def test_une_attribution_disputee_ne_rend_pas_douteuse(self):
        resultat = assess(
            CredibilityInput(
                has_documents=True, from_victim_site=True, disputes=self.DISPUTE
            )
        )
        assert resultat.level is Credibility.CLAIMED
        assert "attribution disputée : victime.co.za (beast, qilin)" in (
            resultat.evidence
        )

    def test_la_presse_garde_son_niveau_et_recoit_le_qualificatif(self):
        resultat = assess(
            CredibilityInput(
                has_documents=True,
                press_confirmed=True,
                republications=self.REPUBLICATION,
            )
        )
        assert resultat.level is Credibility.CONFIRMED
        assert "republication" in resultat.evidence

    def test_sans_document_aucun_qualificatif(self):
        resultat = assess(
            CredibilityInput(has_documents=False, republications=self.REPUBLICATION)
        )
        assert resultat.level is Credibility.NOT_EVALUATED
        assert "republication" not in resultat.evidence

    def test_au_dela_de_trois_on_resume(self):
        """La preuve est tronquee a 500 caracteres en base : une liste coupee
        au milieu d'un nom serait fausse."""
        republications = tuple(
            (f"v{i}.com", "lockbit3", "2023-01-01") for i in range(5)
        )
        resultat = assess(
            CredibilityInput(has_documents=True, republications=republications)
        )
        assert resultat.evidence.count("republication :") == 3
        assert resultat.evidence.endswith("et 2 autre(s)")


class TestChaqueNiveauPorteSaPreuve:
    @pytest.mark.parametrize(
        "faits",
        [
            {"press_confirmed": True},
            {"download_link_gone": True},
            {"publication_status": "published"},
            {"publication_status": "pending"},
            {},
        ],
    )
    def test_preuve_non_vide(self, faits):
        assert assess(CredibilityInput(has_documents=True, **faits)).evidence


class TestVocabulaireTransmisAuLLM:
    def test_tous_les_niveaux_ont_une_phrase(self):
        assert set(LIBELLES_CREDIBILITE) == {c.value for c in Credibility}

    def test_published_reste_une_declaration_du_groupe(self):
        """⚠️ Le modele ne doit pas lire « publiee » comme « verifiee par
        nous » : le projet ne telecharge pas le contenu des fuites."""
        phrase = libelle_credibilite("published").lower()
        assert "affirme" in phrase and "non vérifiée" in phrase

    def test_niveau_inconnu_ne_produit_rien(self):
        assert libelle_credibilite("inconnu") is None
        assert libelle_credibilite(None) is None
