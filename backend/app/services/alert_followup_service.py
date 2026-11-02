"""Ce qui doit se faire SANS attendre qu'un analyste ouvre l'application.

**Resumes pre-generes.** Chaque alerte affichait « Pas encore resumee » : le
livrable exigeait un clic et une minute d'attente. Il doit etre pret a
l'ouverture.

⚠️ NON ARME PAR DEFAUT. La tache existe dans la liste blanche des taches
planifiables ; c'est l'analyste qui cree l'entree de planification s'il la
veut. Une passe LLM sur toutes les alertes ne doit pas demarrer toute seule
parce qu'on a mis a jour le logiciel.

ℹ️ Ce module portait aussi une **notification sortante** (envoi des alertes
graves aux contacts declares). La notion de destinataire a ete retiree du
produit le 2026-09-05 : l'alerte se lit dans l'outil, et le rapport PDF est
transmis par l'analyste.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.pipeline.alerting.summarize import summarize_alert
from app.services.admiralty_service import victim_claims
from app.services.report_service import sujet_alerte

logger = logging.getLogger(__name__)

# Bornes par passe. Un LLM local met ~1 min par resume : sans plafond, la
# tache depasserait sa limite de temps Celery et serait tuee puis rejouee en
# boucle (CONTRIBUTING.md §8).
MAX_RESUMES_PAR_PASSE = 10
MAX_NOTIFICATIONS_PAR_PASSE = 25

# ⚠️ Ne notifier automatiquement que ce qui le merite. Envoyer les 24 alertes
# `medium` du corpus a des organisations tierces les habituerait a ignorer nos
# messages -- le contraire du but.
SEVERITES_NOTIFIEES = ("critical", "high")


def resumer_alertes_en_attente(
    db: Session, model_name: str, *, limite: int = MAX_RESUMES_PAR_PASSE
) -> dict:
    """Genere les resumes manquants des alertes ouvertes, les plus graves d'abord."""
    ordre = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    candidates = [
        alerte
        for alerte in db.query(Alert)
        .filter(Alert.status == "open", Alert.summary.is_(None))
        .all()
    ]
    candidates.sort(key=lambda a: (ordre.get(a.severity, 9), a.created_at))
    candidates = candidates[:limite]

    faits, echecs = 0, 0
    for alerte in candidates:
        try:
            alerte.summary = asyncio.run(
                summarize_alert(
                    alerte,
                    sujet_alerte(db, alerte),
                    model_name,
                    victim_claims(db, alerte),
                )
            )
            db.commit()
            faits += 1
        except Exception:
            # ⚠️ Un modele indisponible ne doit pas faire echouer la passe :
            # le resume est un confort, l'alerte reste le livrable.
            db.rollback()
            logger.warning(
                "Resume impossible pour l'alerte %s", alerte.id, exc_info=True
            )
            echecs += 1
    return {"candidates": len(candidates), "resumees": faits, "echecs": echecs}
