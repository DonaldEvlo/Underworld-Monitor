"""Tache de generation d'alertes planifiee. Wrapper fin (voir CONTRIBUTING.md §3.3)
autour de services/alert_service.py, partage avec le routeur API.

Comble le manque le plus visible du fonctionnement a la demande : les
detections etaient bien produites a chaque collecte, mais aucune alerte n'etait
generee tant que personne ne cliquait sur "Generer les alertes du jour" --
constate en usage reel (corpus complet, 0 alerte en base). Une plateforme dont
le livrable est l'alerte ne peut pas dependre d'un clic."""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.services.alert_service import generate_alerts
from app.services.corroboration_service import (
    CorroborationOutcome,
    corroborate_corpus,
)
from app.services.alert_service import refresh_alert_severities
from app.services.credibility_service import refresh_alert_credibility
from app.services.detection_severity_service import refresh_detection_severities
from app.services.victim_location_service import locate_victims
from app.services.victim_intel_service import (
    refresh_press_coverage,
    apply_effective_facts,
    refresh_victim_intel,
)
from app.worker.celery_app import celery_app
from app.worker.scheduled_guard import run_scheduled

logger = logging.getLogger(__name__)


@celery_app.task(name="alerts.generate")
def generate_alerts_task() -> dict:
    """Enveloppe planifiee : respecte la suspension eventuelle de la tache
    et enregistre son passage (voir worker/scheduled_guard.py). Le travail
    lui-meme est dans `_generate_alerts_task`."""
    return run_scheduled("alerts.generate", _generate_alerts_task)


def _generate_alerts_task() -> dict:
    """Scanne les detections contre les entites surveillees et persiste les
    alertes. Idempotent par (entite, jour) -- voir alert_service.generate_alerts
    : une execution repetee le meme jour complete l'alerte existante au lieu
    d'en creer une nouvelle, ce qui rend cette tache sure a planifier a
    n'importe quelle frequence."""
    db = SessionLocal()
    try:
        # Pays DECLARE des victimes sans domaine localisable (ransomware.live),
        # AVANT la generation : c'est lui qui les fait entrer dans la passe
        # regionale. Enrichissement, donc jamais bloquant.
        try:
            localisation = locate_victims(db)
            if localisation.located:
                logger.info(
                    "Localisation des victimes: %d/%d localisee(s)",
                    localisation.located,
                    localisation.candidates,
                )
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Localisation des victimes: echec, alerting poursuivi")

        alerts = generate_alerts(db)
        logger.info(
            "Alerting planifie: %d alerte(s) creee(s)/mise(s) a jour", len(alerts)
        )

        # Corroboration par un second observateur, dans la foulee : un seul
        # appel clearnet (~23 s) pour toute la passe. Volontairement APRES la
        # persistance des alertes et sans pouvoir la faire echouer -- c'est
        # un enrichissement, le livrable est l'alerte elle-meme. Un
        # RansomLook injoignable laisse simplement les alertes non
        # corroborees (voir corroboration_service).
        #
        # ⚠️ Protegee par un try : la promesse « sans pouvoir la faire echouer »
        # n'etait tenue que pour les pannes RESEAU. Le 2026-09-11, une date
        # d'historique RansomLook sans fuseau a leve un TypeError dans
        # l'indexation -- la tache entiere aurait echoue apres la creation des
        # alertes, sans recalculer les severites.
        try:
            corroboration = corroborate_corpus(db)
        except Exception as exc:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Corroboration: echec, alertes conservees")
            corroboration = CorroborationOutcome(success=False, error=str(exc))
        if corroboration.success:
            logger.info(
                "Corroboration: %d/%d detection(s) confirmee(s), %d alerte(s) corroboree(s)",
                corroboration.detections_corroborated,
                corroboration.detections_checked,
                corroboration.alerts_corroborated,
            )

        # Renseignements par victime (migration 0026), APRES la corroboration
        # dont ils dependent : c'est elle qui attribue le gang, et c'est le
        # gang qui designe l'historique a interroger.
        #
        # ⚠️ ORDRE OBLIGATOIRE : generer -> corroborer -> RENSEIGNER ->
        # recalculer les severites. La nouvelle echelle (2026-09-15) repose sur
        # la date reelle de l'incident et l'exposition d'identifiants, qui
        # vivent sur l'ALERTE et ne sont donc pas connues au moment ou
        # `generate_alerts` la cree : une alerte NAIT en `medium` et sa gravite
        # reelle est etablie ici. Inverser l'ordre rendrait l'echelle muette.
        #
        # Comme la corroboration, jamais bloquant.
        intel: dict = {}
        try:
            resultat_intel = refresh_victim_intel(db)
            intel = {
                "alerts_updated": resultat_intel.alerts_updated,
                "with_attack_date": resultat_intel.with_attack_date,
                "with_credential_exposure": resultat_intel.with_credential_exposure,
            }
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Renseignements par victime: echec, alertes conservees")

        # Confirmation par la presse (migration 0030), APRES la corroboration
        # qui attribue les gangs. Signal de CREDIBILITE, pas de gravite : il
        # ne touche pas a la severite. Jamais bloquant.
        presse: dict = {}
        try:
            resultat_presse = refresh_press_coverage(db)
            presse = {
                "alerts_confirmed": resultat_presse.alerts_confirmed,
                "newly_confirmed": resultat_presse.newly_confirmed,
                "gangs_unavailable": resultat_presse.gangs_unavailable,
            }
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Confirmation par la presse: echec, alertes conservees")

        # Credibilite (migration 0031), APRES la presse dont elle depend. Axe
        # DISTINCT de la gravite : ne la modifie pas. Jamais bloquant.
        credibilite: dict = {}
        try:
            credibilite = refresh_alert_credibility(db)
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Credibilite des alertes: echec, alertes conservees")

        # Pays et secteur EFFECTIFS (migration 0033) : correction de l'analyste,
        # sinon declaration de l'organisation, sinon tiers. ⚠️ AVANT le
        # recalcul des severites, qui lit le secteur effectif. Jamais bloquant.
        try:
            apply_effective_facts(db)
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Pays et secteur effectifs: echec, alertes conservees")

        # Recalcul des severites des ALERTES, une fois les renseignements
        # connus. ⚠️ Portee volontairement GLOBALE ici (aucun `alert_ids`) :
        # c'est la passe de production. Le parametre existe pour borner les
        # appels de test, apres qu'un test eut reecrit les 33 alertes reelles.
        try:
            recalcul = refresh_alert_severities(db, apply=True)
            if recalcul["modifiees"]:
                logger.info(
                    "Severite des alertes: %d/%d modifiee(s)",
                    recalcul["modifiees"],
                    recalcul["examinees"],
                )
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            db.rollback()
            logger.exception("Severite des alertes: echec du recalcul")

        # Severite persistee sur les DETECTIONS, apres la corroboration (dont
        # elle depend) : c'est ce qui donne une severite aux institutions hors
        # perimetre de surveillance, que `generate_alerts` ignore par
        # construction. Ne cree aucune alerte -- voir
        # detection_severity_service.
        #
        # Comme la corroboration, cet enrichissement ne doit jamais faire
        # echouer la tache : le livrable est l'alerte.
        severities: dict = {}
        try:
            severities = refresh_detection_severities(db)
        except Exception:  # noqa: BLE001 - enrichissement non bloquant
            logger.exception(
                "Severite des detections: echec du recalcul, alertes conservees"
            )

        return {
            "victim_intel": intel,
            "press": presse,
            "credibility": credibilite,
            "alerts": [
                {
                    "id": str(a.id),
                    "entity_id": str(a.entity_id),
                    "severity": a.severity,
                    "detection_count": len(a.detections),
                }
                for a in alerts
            ],
            "corroboration": {
                "success": corroboration.success,
                "feed_size": corroboration.feed_size,
                "detections_corroborated": corroboration.detections_corroborated,
                "alerts_corroborated": corroboration.alerts_corroborated,
            },
            "detection_severities": severities,
        }
    finally:
        db.close()


@celery_app.task(name="alerts.summarize_pending")
def summarize_pending_task() -> dict:
    """Pre-genere les resumes manquants des alertes ouvertes.

    ⚠️ Le resume est le LIVRABLE lu par l'analyste : l'exiger d'un clic et
    d'une minute d'attente le rendait absent au moment ou l'on en a besoin.
    """
    return run_scheduled("alerts.summarize_pending", _summarize_pending_task)


def _summarize_pending_task() -> dict:
    from app.api.routers.llm import get_selected_model
    from app.services.alert_followup_service import resumer_alertes_en_attente

    db = SessionLocal()
    try:
        return resumer_alertes_en_attente(db, get_selected_model())
    finally:
        db.close()
