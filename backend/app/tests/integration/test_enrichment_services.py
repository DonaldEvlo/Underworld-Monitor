"""Services d'enrichissement des alertes, sur base reelle et transaction
annulee : corroboration, renseignements par victime, presse, credibilite,
rapport PDF, et ordre de la chaine `alerts.generate`.

Ils etaient les moins couverts du depot (14 a 26 % au 2026-09-25) alors
qu'ils portent le livrable. Tout appel reseau est remplace -- flux et
historiques RansomLook, ransomware.live, LLM : ces tests ne sortent jamais du
poste (regle 3), et un echec d'agregateur doit etre SIMULE pour etre teste.

Les comportements verrouilles sont ceux que le CONTRIBUTING.md documente comme des
lecons, pas des details d'implementation :
  - une absence de mesure n'est JAMAIS ecrite comme un resultat negatif ;
  - un enrichissement ne fait JAMAIS echouer l'alerting ;
  - la portee (`alert_id`, `alert_ids`) borne reellement l'ecriture.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.db.models.alert import Alert
from app.db.session import SessionLocal
from app.pipeline.enrich.ransomlook_corroboration import (
    OBSERVER_RANSOMLOOK,
    OBSERVER_RANSOMWARE_LIVE,
    gang_slug_for_source,
)
from app.services import corroboration_service as corro
from app.services import credibility_service
from app.services import report_service
from app.services import victim_intel_service as intel
from app.tests.integration import factories as f

ARTICLE = "https://presse.example.org/cyberattaque"


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def reseau(monkeypatch):
    """Remplace TOUS les appels reseau de la corroboration. Chaque test fixe
    ce que chaque observateur « repond » pour chaque gang ; `None` = observateur
    injoignable (absence de mesure), `[]` = gang non suivi."""
    reponses = {"ransomlook": {}, "rwl": {}, "flux": []}
    monkeypatch.setattr(corro, "fetch_ransomlook_posts", lambda _url: reponses["flux"])
    monkeypatch.setattr(
        corro, "_historique", lambda gang: reponses["ransomlook"].get(gang, [])
    )
    monkeypatch.setattr(
        corro, "payload_rwl", lambda gang: reponses["rwl"].get(gang, [])
    )
    # Les renseignements par victime importent `payload_rwl` a part.
    monkeypatch.setattr(
        intel, "payload_rwl", lambda gang: reponses["rwl"].get(gang, [])
    )
    return reponses


def _annonce_ransomlook(domaine: str) -> dict:
    return {
        "post_title": domaine,
        "discovered": "2026-09-01 10:00:00",
        "screen": f"screenshots/test/{domaine}.png",
    }


def _victime_rwl(domaine: str, **champs) -> dict:
    return {
        "victim": domaine,
        "domain": domaine,
        "discovered": "2026-09-01T10:00:00+00:00",
        "screenshot": f"https://images.ransomware.live/{domaine}.png",
        **champs,
    }


# --------------------------------------------------------------------------
# Corroboration
# --------------------------------------------------------------------------


class TestCorroboration:
    def test_victime_vue_par_les_deux_observateurs(self, db, reseau):
        src, _, det, alerte = f.victime_alertee(db)
        gang = gang_slug_for_source(src.name)
        reseau["ransomlook"][gang] = [_annonce_ransomlook(det.value_masked)]
        reseau["rwl"][gang] = [_victime_rwl(det.value_masked)]

        resultat = corro.corroborate_corpus(db, alert_id=alerte.id)

        assert resultat.success
        db.refresh(det)
        db.refresh(alerte)
        assert det.corroboration_status == "corroborated"
        assert alerte.corroboration_status == "corroborated"
        assert alerte.corroborated_group == gang
        assert set(alerte.corroboration_observers) == {
            OBSERVER_RANSOMLOOK,
            OBSERVER_RANSOMWARE_LIVE,
        }
        # Une preuve consultable, en clearnet.
        assert alerte.corroboration_evidence_url.startswith("https://")

    def test_absente_chez_des_observateurs_qui_ont_repondu_exclusive(self, db, reseau):
        src, _, det, alerte = f.victime_alertee(db)
        gang = gang_slug_for_source(src.name)
        reseau["ransomlook"][gang] = [_annonce_ransomlook("autre-victime.com")]
        reseau["rwl"][gang] = [_victime_rwl("autre-victime.com")]

        corro.corroborate_corpus(db, alert_id=alerte.id)

        db.refresh(det)
        assert det.corroboration_status == "exclusive"

    def test_observateur_injoignable_jamais_ecrit_comme_exclusive(self, db, reseau):
        """⚠️ « Vue par nous seuls » exige que TOUS les observateurs aient
        repondu. ransomware.live injoignable -> statut conserve."""
        src, _, det, alerte = f.victime_alertee(db)
        gang = gang_slug_for_source(src.name)
        reseau["ransomlook"][gang] = [_annonce_ransomlook("autre-victime.com")]
        reseau["rwl"][gang] = None

        resultat = corro.corroborate_corpus(db, alert_id=alerte.id)

        db.refresh(det)
        assert det.corroboration_status is None
        assert gang in resultat.histories_unavailable

    def test_flux_ransomlook_en_panne_rien_n_est_ecrit(self, db, monkeypatch):
        _, _, det, alerte = f.victime_alertee(db)

        def panne(_url):
            raise ConnectionError("RansomLook injoignable")

        monkeypatch.setattr(corro, "fetch_ransomlook_posts", panne)
        resultat = corro.corroborate_corpus(db, alert_id=alerte.id)

        assert resultat.success is False
        db.refresh(det)
        db.refresh(alerte)
        assert det.corroboration_status is None
        assert alerte.corroboration_status is None

    def test_forum_sans_objet(self, db, reseau):
        """Un domaine CITE sur un forum n'est pas une victime revendiquee."""
        src = f.source(db, name=f"{f.unique('FORUM')} (Dark)", type_="forum")
        doc = f.document(db, src, collector="xenforo_latest")
        det = f.detection(db, doc)
        alerte = f.alert(db, [det], ent=f.entity(db, domain=det.value_masked))

        corro.corroborate_corpus(db, alert_id=alerte.id)

        db.refresh(det)
        assert det.corroboration_status == "not_applicable"


# --------------------------------------------------------------------------
# Renseignements par victime et presse
# --------------------------------------------------------------------------


class TestRenseignementsEtPresse:
    def test_secteur_pays_et_presse_renseignes(self, db, reseau):
        src, _, det, alerte = f.victime_alertee(db)
        gang = gang_slug_for_source(src.name)
        alerte.corroborated_group = gang
        alerte.corroborated_groups = [gang]
        db.commit()
        reseau["rwl"][gang] = [
            _victime_rwl(
                det.value_masked,
                activity="Government & Defense",
                country="ZA",
                attackdate="2026-09-10T00:00:00+00:00",
                press={"link": "https://www.ransomware.live/id/x", "source": ARTICLE},
            )
        ]

        intel.refresh_victim_intel(db, alert_id=alerte.id)
        presse = intel.refresh_press_coverage(db, alert_ids=[alerte.id])

        db.refresh(alerte)
        assert alerte.victim_sector == "Government & Defense"
        assert alerte.victim_country == "ZA"
        assert alerte.intel_refreshed_at is not None
        assert alerte.press_source_url == ARTICLE
        assert presse.newly_confirmed == 1

    def test_date_d_attaque_la_plus_ancienne_revendication(self, db, reseau):
        """⚠️ Un republieur date sinon une vieille fuite du jour de sa
        republication (ORION reprend des victimes LockBit jusqu'a trois ans
        apres, mesure du 2026-09-30) -- assez pour la rendre « fraiche »."""
        _, _, det, alerte = f.victime_alertee(db)
        alerte.corroborated_group = "orion"
        alerte.corroborated_groups = ["orion", "lockbit3"]
        db.commit()
        reseau["rwl"]["orion"] = [
            _victime_rwl(det.value_masked, attackdate="2026-09-20T00:00:00+00:00")
        ]
        reseau["rwl"]["lockbit3"] = [
            _victime_rwl(det.value_masked, attackdate="2023-09-10T00:00:00+00:00")
        ]

        intel.refresh_victim_intel(db, alert_id=alerte.id)

        db.refresh(alerte)
        assert alerte.victim_attack_date.date().isoformat() == "2023-09-10"

    def test_date_du_principal_inconnue_on_n_adopte_pas_celle_d_un_autre(
        self, db, reseau
    ):
        """La regle ne fait que VIEILLIR une date connue : adopter celle d'un
        autre gang pourrait adopter celle du republieur, donc une date fausse
        et « fraiche »."""
        _, _, det, alerte = f.victime_alertee(db)
        alerte.corroborated_group = "lockbit3"
        alerte.corroborated_groups = ["lockbit3", "orion"]
        db.commit()
        reseau["rwl"]["lockbit3"] = [_victime_rwl(det.value_masked)]
        reseau["rwl"]["orion"] = [
            _victime_rwl(det.value_masked, attackdate="2026-09-20T00:00:00+00:00")
        ]

        intel.refresh_victim_intel(db, alert_id=alerte.id)

        db.refresh(alerte)
        assert alerte.intel_refreshed_at is not None
        assert alerte.victim_attack_date is None

    def test_victime_ransomlook_localisee_recoit_ses_renseignements(self, db, reseau):
        """⚠️ Un document RansomLook n'est jamais corrobore (auto-confirmation) :
        sans la lecture du gang sur la source et du domaine declare, l'alerte
        de la Exemple Defence Force restait sans secteur ni date, donc
        `medium` au lieu de CRITICAL (mesure du 2026-09-30)."""
        src = f.source(db)
        doc = f.document(
            db,
            src,
            collector="ransomlook",
            title="Exemple Defence Force",
            source_meta={
                "group_name": "ransomhouse",
                "victim_country": "NA",
                "victim_domain": "defense-exemple.gov.na",
                "victim_location_source": "ransomware.live",
            },
        )
        det = f.detection(
            db, doc, type_="organization", value_masked="Exemple Defence Force"
        )
        alerte = f.alert(db, [det], region=f.unique("Region-"))
        assert alerte.corroborated_group is None
        reseau["rwl"]["ransomhouse"] = [
            _victime_rwl(
                "www.defense-exemple.gov.na",
                victim="Exemple Defence Force",
                activity="Government & Defense",
                country="NA",
                attackdate="2026-09-12T00:00:00+00:00",
            )
        ]

        intel.refresh_victim_intel(db, alert_id=alerte.id)

        db.refresh(alerte)
        assert alerte.victim_sector == "Government & Defense"
        assert alerte.victim_attack_date.date().isoformat() == "2026-09-12"

    def test_ransomware_live_injoignable_rien_n_est_ecrit(self, db, reseau):
        """⚠️ Ecrire des zeros ferait passer « non mesure » pour « aucune
        exposition »."""
        src, _, _, alerte = f.victime_alertee(db)
        gang = gang_slug_for_source(src.name)
        alerte.corroborated_group = gang
        db.commit()
        reseau["rwl"][gang] = None

        resultat = intel.refresh_victim_intel(db, alert_id=alerte.id)

        db.refresh(alerte)
        assert resultat.success is False
        assert alerte.intel_refreshed_at is None
        assert alerte.victim_sector is None


# --------------------------------------------------------------------------
# Credibilite
# --------------------------------------------------------------------------


class TestCredibilite:
    def test_statut_lu_sur_toute_la_victime(self, db):
        """Le libelle « publiee » peut ne figurer que sur un AUTRE document de
        la meme victime (meme source, meme URL) que celui de la detection."""
        src, doc, _, alerte = f.victime_alertee(db)
        f.document(
            db,
            src,
            url=doc.url,
            source_meta={
                "publication_status": "published",
                "publication_evidence": "badge « PUBLISHED »",
            },
        )

        credibility_service.refresh_alert_credibility(db, alert_ids=[alerte.id])

        db.refresh(alerte)
        assert alerte.credibility_level == "published"
        assert "PUBLISHED" in alerte.credibility_evidence

    def test_presse_l_emporte(self, db):
        _, _, _, alerte = f.victime_alertee(db, publication_status="pending")
        alerte.press_confirmed_at = datetime.now(timezone.utc)
        db.commit()

        credibility_service.refresh_alert_credibility(db, alert_ids=[alerte.id])

        db.refresh(alerte)
        assert alerte.credibility_level == "confirmed"

    def test_annonce_de_forum_revendiquee(self, db):
        src = f.source(db, name=f"{f.unique('FORUM')} (Dark)", type_="forum")
        doc = f.document(db, src, collector="xenforo_latest")
        det = f.detection(db, doc)
        alerte = f.alert(db, [det], ent=f.entity(db, domain=det.value_masked))

        credibility_service.refresh_alert_credibility(db, alert_ids=[alerte.id])

        db.refresh(alerte)
        assert alerte.credibility_level == "claimed"
        assert "forum" in alerte.credibility_evidence

    def test_idempotent_et_borne(self, db):
        _, _, _, alerte = f.victime_alertee(db, publication_status="published")

        premiere = credibility_service.refresh_alert_credibility(
            db, alert_ids=[alerte.id]
        )
        seconde = credibility_service.refresh_alert_credibility(
            db, alert_ids=[alerte.id]
        )

        assert premiere["examinees"] == 1  # la portee borne l'ecriture
        assert premiere["modifiees"] == 1
        assert seconde["modifiees"] == 0

    def test_observations_pour_la_validation(self, db, reseau):
        src, _, det, _ = f.victime_alertee(db, publication_status="published")
        gang = gang_slug_for_source(src.name)
        reseau["rwl"][gang] = [
            _victime_rwl(det.value_masked, press={"link": ARTICLE, "source": ARTICLE})
        ]

        observations, couverture = credibility_service.observations_for_validation(db)

        miennes = [o for o in observations if o.gang == gang]
        assert len(miennes) == 1
        assert (miennes[0].status, miennes[0].press) == ("published", True)
        assert couverture["victimes"] >= 1


# --------------------------------------------------------------------------
# Rapport PDF
# --------------------------------------------------------------------------


class TestRapport:
    def test_llm_indisponible_le_rapport_est_quand_meme_produit(self, db, monkeypatch):
        """Faits, sources et preuves sont produits par le code : la synthese
        n'est qu'un confort de lecture."""

        async def panne(*_a, **_k):
            raise ConnectionError("Ollama injoignable")

        monkeypatch.setattr(report_service, "generate_response", panne)
        _, _, _, alerte = f.victime_alertee(db)
        # Caracteres hors latin-1, typiques d'une note ou d'un LLM.
        alerte.analyst_note = "Traitée — « vérifiée » l’après-midi…"
        db.commit()

        pdf, nom = asyncio.run(report_service.generer_rapport_pdf(db, alerte, "test"))

        assert pdf[:4] == b"%PDF"
        assert nom.startswith("rapport-") and nom.endswith(".pdf")

    def test_la_synthese_du_llm_est_integree(self, db, monkeypatch):
        vus = {}

        async def llm(_modele, contenu, _question, **_k):
            vus["contenu"] = contenu
            return "Synthese de test."

        monkeypatch.setattr(report_service, "generate_response", llm)
        _, _, det, alerte = f.victime_alertee(db)

        asyncio.run(report_service.generer_rapport_pdf(db, alerte, "test"))

        # Le LLM recoit des faits, jamais l'empreinte d'une valeur.
        assert det.value_hash not in vus["contenu"]
        assert "Organisation concernée" in vus["contenu"]


# --------------------------------------------------------------------------
# Chaine alerts.generate
# --------------------------------------------------------------------------


class TestChaineAlerting:
    def test_un_enrichissement_en_panne_ne_fait_pas_echouer_l_alerting(
        self, db, monkeypatch
    ):
        """⚠️ Le livrable est l'alerte. Corroboration, renseignements et presse
        levent tous : la tache doit aboutir et calculer la credibilite."""
        from app.worker.tasks import alert_tasks

        def panne(*_a, **_k):
            raise RuntimeError("enrichissement en panne")

        monkeypatch.setattr(alert_tasks, "corroborate_corpus", panne)
        monkeypatch.setattr(alert_tasks, "refresh_victim_intel", panne)
        monkeypatch.setattr(alert_tasks, "refresh_press_coverage", panne)

        resultat = alert_tasks._generate_alerts_task()

        assert "alerts" in resultat
        assert resultat["credibility"]["examinees"] == db.query(Alert).count()
