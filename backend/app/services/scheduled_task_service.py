"""Planification : quelles actions sont automatisees, a quels moments.

Depuis la migration 0021, la table `scheduled_tasks` est la SOURCE DE VERITE de
Celery Beat (voir `worker/db_scheduler.py`) : ajouter, modifier ou supprimer une
entree prend effet sans toucher au code ni recreer le service `beat`.

⚠️ LISTE BLANCHE D'ACTIONS. `action` ne peut prendre qu'une valeur de
`KNOWN_ACTIONS`. Accepter un nom libre reviendrait a offrir l'execution de
n'importe quelle tache Celery enregistree a tout utilisateur authentifie --
c'est-a-dire de l'execution de code a distance derriere un formulaire.

⚠️ LA FILE N'EST PAS CHOISIE PAR L'UTILISATEUR : elle decoule de l'action.
`collect.dread` (~25 min) et `links.check_corpus` (~2 h) ont leur propre file
parce que le worker principal ne prend qu'une tache a la fois ; les placer sur
la file par defaut bloquerait la collecte ET l'alerting horaire, donc le
livrable du produit (CONTRIBUTING.md §8).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.scheduled_task import ScheduledTask

logger = logging.getLogger(__name__)


# Actions automatisables. La cle est le nom Celery reel ; `queue` est imposee.
KNOWN_ACTIONS: dict[str, dict] = {
    "collect.all_active_sources": {
        "label": "Collecter toutes les sources actives",
        "queue": "celery",
        "description": (
            "Programme une collecte par source active. Dread en est exclu : "
            "il a sa propre action."
        ),
    },
    "collect.victim_sources": {
        "label": "Collecter les sites de fuite",
        "queue": "celery",
        "description": (
            "Programme une collecte des seules sources qui publient leurs "
            "victimes (sites de fuite, AKIRA, RansomLook) : c'est la qu'une "
            "victime apparait en premier. Plus legere que la collecte generale."
        ),
    },
    "alerts.generate": {
        "label": "Generer les alertes",
        "queue": "celery",
        "description": (
            "Confronte les detections aux entites surveillees, corrobore et "
            "recalcule les severites. Peu couteux, aucun acces reseau."
        ),
    },
    "collect.dread": {
        "label": "Collecter Dread",
        "queue": "dread",
        "description": (
            "Collecte longue (~25 min) sur file dediee, pour ne pas bloquer "
            "la collecte ni l'alerting."
        ),
    },
    "alerts.summarize_pending": {
        "label": "Pre-generer les resumes d'alerte",
        "queue": "celery",
        "description": (
            "Redige les resumes manquants des alertes ouvertes, les plus graves "
            "d'abord. Sans elle, chaque alerte affiche « pas encore resumee » "
            "jusqu'a ce qu'un analyste clique et attende."
        ),
    },
    "links.check_corpus": {
        "label": "Verifier la vivacite des liens",
        "queue": "links",
        "description": (
            "Verifie si les liens cites repondent encore. Tres longue "
            "(jusqu'a ~2 h), sur file dediee."
        ),
    },
    "sources.check_addresses_sites": {
        "label": "Reperer les changements d'adresse (sites)",
        "queue": "links",
        "description": (
            "Lit la page de chaque source active via Tor et ses documents "
            "recents : un avis de migration ou un nouveau domaine annonce est "
            "verifie, et la source bascule si la nouvelle adresse publie les "
            "memes victimes."
        ),
    },
    "sources.check_addresses_deepdarkcti": {
        "label": "Reperer les changements d'adresse (deepdarkCTI)",
        "queue": "links",
        "description": (
            "Confronte nos adresses aux listes fastfire/deepdarkCTI (forums, "
            "sites de gangs) : si la notre n'est plus ONLINE, l'autre adresse "
            "du meme nom est verifiee avant toute bascule."
        ),
    },
}

# Un champ crontab accepte par Celery : "*", "5", "6,18", "*/15", "1-5".
_CRON = re.compile(r"^(\*|\d+|\d+-\d+|\*/\d+|(\d+)(,\d+)*)$")


class ScheduleError(ValueError):
    """Entree de planification invalide -- remontee telle quelle a l'API."""


def validate_action(action: str) -> None:
    if action not in KNOWN_ACTIONS:
        raise ScheduleError(
            f"Action inconnue : {action}. Seules les actions prevues sont "
            "automatisables."
        )


def _valeurs(champ: str) -> list[int]:
    """Entiers designes par un champ crontab. Vide pour « * » et « */n »."""
    champ = champ.strip()
    if champ == "*" or champ.startswith("*/"):
        return []
    nombres: list[int] = []
    for morceau in champ.split(","):
        if "-" in morceau:
            debut, fin = morceau.split("-", 1)
            nombres.extend(range(int(debut), int(fin) + 1))
        else:
            nombres.append(int(morceau))
    return nombres


def validate_cron(minute: str, hour: str, day_of_week: str) -> None:
    """Refuse a l'ECRITURE ce que l'ordonnanceur ecarterait en silence.

    ⚠️ Les bornes comptent autant que la forme. « jour 9 » passe l'expression
    reguliere mais fait lever `crontab()` au chargement du calendrier :
    l'entree serait alors ecartee par `db_scheduler`, journalisee dans un log
    que personne ne lit, et l'analyste verrait sa collecte simplement ne jamais
    se declencher. On refuse ici, la ou il peut corriger.
    """
    for nom, valeur, borne_max, exemple in (
        ("minute", minute, 59, "0, 30, 0,30, */15"),
        ("heure", hour, 23, "6, 6,18, */4, * (toutes)"),
        ("jour de la semaine", day_of_week, 6, "* (tous), 1-5, 0,6 (0 = dimanche)"),
    ):
        if not valeur or not _CRON.match(valeur.strip()):
            raise ScheduleError(
                f"Champ {nom} invalide : « {valeur} ». Formes acceptees : "
                f"{exemple}."
            )
        hors_bornes = [n for n in _valeurs(valeur) if n > borne_max]
        if hors_bornes:
            raise ScheduleError(
                f"Champ {nom} hors bornes : {hors_bornes[0]}. "
                f"Valeurs attendues entre 0 et {borne_max}."
            )


_NOMS_JOURS = [
    "dimanche",
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
]


def _jours_lisibles(champ: str) -> str:
    """« 1-5 » ne veut rien dire pour un analyste ; « du lundi au vendredi » si."""
    jours = sorted(set(_valeurs(champ)))
    if not jours or len(jours) == 7:
        return ""
    if jours == [1, 2, 3, 4, 5]:
        return ", du lundi au vendredi"
    if jours == [0, 6]:
        return ", le week-end"
    noms = [_NOMS_JOURS[j] for j in jours if 0 <= j < 7]
    return ", le " + " et ".join(noms) if len(noms) == 1 else ", les " + ", ".join(noms)


def describe_schedule(tache: ScheduledTask) -> str:
    """Horaire en clair, tel que Beat l'appliquera."""
    jours = _jours_lisibles(tache.cron_day_of_week)
    minute = tache.cron_minute.strip()
    heure = tache.cron_hour.strip()

    if heure == "*":
        return f"toutes les heures a la minute {minute}{jours}"
    if heure.startswith("*/"):
        return f"toutes les {heure[2:]} heures, a la minute {minute}{jours}"

    heures = _valeurs(heure)
    minutes = _valeurs(minute)
    if heures and len(minutes) == 1:
        # « a 6,18 h 17 » se lit mal : on ecrit les passages reels.
        passages = " et ".join(f"{h:02d}:{minutes[0]:02d}" for h in heures)
        return f"a {passages}{jours}"
    return f"a {heure} h {minute}{jours}"


def list_tasks(db: Session) -> list[ScheduledTask]:
    return (
        db.query(ScheduledTask)
        .order_by(ScheduledTask.action, ScheduledTask.label)
        .all()
    )


def get(db: Session, task_id) -> ScheduledTask | None:
    return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()


def create(
    db: Session,
    *,
    label: str,
    action: str,
    cron_minute: str,
    cron_hour: str,
    cron_day_of_week: str = "*",
    enabled: bool = True,
) -> ScheduledTask:
    validate_action(action)
    validate_cron(cron_minute, cron_hour, cron_day_of_week)
    label = label.strip()
    if not label:
        raise ScheduleError("Le nom ne peut pas etre vide.")
    if db.query(ScheduledTask).filter(ScheduledTask.task_name == label).first():
        raise ScheduleError(f"Une entree nommee « {label} » existe deja.")

    tache = ScheduledTask(
        task_name=label,
        label=label,
        action=action,
        cron_minute=cron_minute.strip(),
        cron_hour=cron_hour.strip(),
        cron_day_of_week=cron_day_of_week.strip(),
        # ⚠️ Imposee par l'action, jamais choisie : une tache longue placee sur
        # la file par defaut bloquerait l'alerting.
        queue=KNOWN_ACTIONS[action]["queue"],
        enabled=enabled,
    )
    db.add(tache)
    db.commit()
    db.refresh(tache)
    return tache


def update(db: Session, tache: ScheduledTask, **champs) -> ScheduledTask:
    if "action" in champs and champs["action"] is not None:
        validate_action(champs["action"])
        tache.action = champs["action"]
        tache.queue = KNOWN_ACTIONS[tache.action]["queue"]

    minute = champs.get("cron_minute") or tache.cron_minute
    heure = champs.get("cron_hour") or tache.cron_hour
    jour = champs.get("cron_day_of_week") or tache.cron_day_of_week
    validate_cron(minute, heure, jour)
    tache.cron_minute, tache.cron_hour, tache.cron_day_of_week = (
        minute.strip(),
        heure.strip(),
        jour.strip(),
    )

    if champs.get("label"):
        nouveau = champs["label"].strip()
        existant = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.task_name == nouveau, ScheduledTask.id != tache.id)
            .first()
        )
        if existant:
            raise ScheduleError(f"Une entree nommee « {nouveau} » existe deja.")
        tache.label = nouveau
        tache.task_name = nouveau

    if champs.get("enabled") is not None:
        tache.enabled = champs["enabled"]

    db.commit()
    db.refresh(tache)
    return tache


def delete(db: Session, tache: ScheduledTask) -> None:
    db.delete(tache)
    db.commit()


def is_enabled(db: Session, action: str) -> bool:
    """Au moins une entree ACTIVE existe-t-elle pour cette action ?

    ⚠️ Verification cote tache, en plus du filtre de l'ordonnanceur : une
    entree peut etre suspendue entre le chargement du calendrier et le
    declenchement.

    ⚠️ En cas d'erreur, repond OUI. Une tache planifiee ne doit pas cesser de
    tourner parce que la table est indisponible : le livrable du produit est
    l'alerte, pas le confort de reglage.
    """
    try:
        return (
            db.query(ScheduledTask)
            .filter(ScheduledTask.action == action, ScheduledTask.enabled.is_(True))
            .first()
            is not None
        )
    except Exception:
        logger.exception("Etat de %s illisible : execution maintenue", action)
        return True


def record_run(
    db: Session,
    action: str,
    *,
    status: str,
    duration_seconds: int | None = None,
    detail: str | None = None,
) -> None:
    """Enregistre le passage sur TOUTES les entrees de cette action.

    Plusieurs entrees peuvent partager une action (« Collecte du matin » et
    « Collecte du soir ») : Beat ne dit pas laquelle a declenche, on marque
    donc l'action entiere. Le dernier passage se lit alors « cette action a
    tourne », ce qui est l'information utile.

    ⚠️ Ne doit JAMAIS faire echouer la tache : c'est une statistique, pas le
    livrable.
    """
    try:
        maintenant = datetime.now(timezone.utc)
        for tache in db.query(ScheduledTask).filter(ScheduledTask.action == action):
            tache.last_run_at = maintenant
            tache.last_status = status
            tache.last_duration_seconds = duration_seconds
            tache.last_detail = (detail or "")[:255] or None
        db.commit()
    except Exception:
        logger.exception("Passage de %s non enregistre", action)
        db.rollback()
