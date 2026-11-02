"""Garde commun aux taches planifiees : suspension et journal de passage.

Facteur commun des quatre taches de `worker/schedules.py`, pour que la
verification du drapeau et l'enregistrement du passage ne soient pas
reecrits -- et surtout pas OUBLIES -- dans chacune.

⚠️ Beat continue de declencher une tache suspendue : c'est la tache qui se
retire. Ce sens-la ne demande aucune reconfiguration de Beat et survit a son
redemarrage, contrairement a une modification du calendrier.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.db.session import SessionLocal
from app.services.scheduled_task_service import is_enabled, record_run


def run_scheduled(action: str, travail: Callable[[], Any]) -> Any:
    """Execute `travail` si la tache est active, et enregistre son passage.

    Retourne `{"skipped": True}` quand la tache est suspendue -- une reponse
    explicite, distinguable d'un resultat vide.

    ⚠️ Le journal ne doit jamais faire echouer la tache : `record_run` avale
    ses propres erreurs. Une exception du TRAVAIL, en revanche, est
    enregistree PUIS relancee -- Celery doit la voir pour ses propres
    mecanismes (reprise, journalisation).
    """
    db = SessionLocal()
    try:
        if not is_enabled(db, action):
            record_run(db, action, status="skipped", detail="tache suspendue")
            return {"skipped": True, "reason": "tache suspendue"}
    finally:
        db.close()

    debut = time.monotonic()
    try:
        resultat = travail()
    except Exception as exc:
        db = SessionLocal()
        try:
            record_run(
                db,
                action,
                status="error",
                duration_seconds=max(0, round(time.monotonic() - debut)),
                detail=str(exc),
            )
        finally:
            db.close()
        raise

    db = SessionLocal()
    try:
        record_run(
            db,
            action,
            status="success",
            duration_seconds=max(0, round(time.monotonic() - debut)),
            detail=_resume(resultat),
        )
    finally:
        db.close()
    return resultat


def _resume(resultat: Any) -> str | None:
    """Une ligne lisible de ce que la tache a produit, pour l'affichage.

    ⚠️ Les listes sont resumees par leur TAILLE, pas ignorees. Une premiere
    version ne gardait que les valeurs scalaires : le resultat de
    `alerts.generate` ne contenant que des listes et des dictionnaires, la
    colonne restait vide et le passage paraissait sans effet.
    """
    if not isinstance(resultat, dict):
        return None
    morceaux: list[str] = []
    for cle, valeur in resultat.items():
        if isinstance(valeur, (int, float, str, bool)):
            morceaux.append(f"{cle}={valeur}")
        elif isinstance(valeur, (list, tuple, set)):
            morceaux.append(f"{cle}={len(valeur)}")
        elif isinstance(valeur, dict):
            # Un niveau d'imbrication suffit : au-dela, la ligne devient
            # illisible et ce n'est plus un resume.
            interne = ", ".join(
                f"{k}={v}"
                for k, v in valeur.items()
                if isinstance(v, (int, float, str, bool))
            )
            if interne:
                morceaux.append(f"{cle}({interne})")
    return ", ".join(morceaux) if morceaux else None
