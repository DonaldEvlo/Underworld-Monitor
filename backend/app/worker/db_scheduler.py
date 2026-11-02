"""Ordonnanceur Celery Beat lisant sa planification EN BASE.

Beat lit normalement `beat_schedule` au demarrage : les horaires etaient donc
figes dans `worker/schedules.py`, et les changer exigeait de recreer le
service. Cet ordonnanceur lit la table `scheduled_tasks`, ce qui rend
l'ajout, la modification et la suppression d'un moment de collecte
immediatement effectifs depuis l'interface.

⚠️ Seules les entrees ACTIVES sont chargees, et l'action est resolue par la
liste blanche `KNOWN_ACTIONS` : la base ne peut pas faire declencher une tache
Celery arbitraire, meme si son contenu etait altere.

⚠️ Le calendrier est relu periodiquement (`max_interval`). Un changement n'est
donc pas instantane : il prend effet au prochain rechargement, au plus tard
apres `SCHEDULE_RELOAD_SECONDS`. Une relecture a chaque tick coûterait une
requete par seconde pour un reglage qui bouge quelques fois par an.
"""

from __future__ import annotations

import logging
import time

from celery.beat import ScheduleEntry, Scheduler
from celery.schedules import crontab

from app.db.session import SessionLocal
from app.db.models.scheduled_task import ScheduledTask
from app.services.scheduled_task_service import KNOWN_ACTIONS
from app.worker.schedules import seed_default_schedule

logger = logging.getLogger(__name__)

# Intervalle de relecture du calendrier, en secondes.
#
# 60 s : un compromis entre reactivite percue (l'analyste voit son changement
# pris en compte dans la minute) et charge inutile. Beat reveille de toute
# facon son boucle a cet intervalle au maximum.
SCHEDULE_RELOAD_SECONDS = 60


class DatabaseScheduler(Scheduler):
    """Calendrier alimente par `scheduled_tasks`."""

    def __init__(self, *args, **kwargs):
        self._schedule: dict[str, ScheduleEntry] = {}
        self._dernier_chargement = 0.0
        # ⚠️ `max_interval` est un ATTRIBUT que Celery ecrit lui-meme dans
        # `Scheduler.__init__` : en faire une propriete en lecture seule fait
        # echouer le demarrage de Beat (constate). On se contente donc de
        # fournir la valeur par defaut, que la ligne de commande peut encore
        # surcharger.
        if not kwargs.get("max_interval"):
            kwargs["max_interval"] = SCHEDULE_RELOAD_SECONDS
        super().__init__(*args, **kwargs)

    def setup_schedule(self) -> None:
        # ⚠️ Amorcage appele ICI et nulle part ailleurs : au demarrage de Beat,
        # une seule fois, et jamais a l'import du module (l'API et les workers
        # importent `celery_app` -- amorcer a l'import ecrirait en base depuis
        # chacun d'eux). N'ecrit que si la table est ENTIEREMENT vide.
        seed_default_schedule()
        self._charger()

    def get_schedule(self) -> dict[str, ScheduleEntry]:
        """Calendrier courant, relu si le delai de relecture est ecoule.

        ⚠️ C'EST LE SEUL POINT DE RELECTURE FIABLE. `sync()` semblait le bon
        endroit, mais Celery ne l'appelle que toutes les 180 s ET seulement par
        certains chemins : une modification d'horaire n'etait PAS reprise
        (mesure -- aucun rechargement apres 75 s). `tick()`, lui, consulte
        cette propriete a chaque boucle ; le garde temporel maintient donc
        exactement une requete par minute.
        """
        if time.monotonic() - self._dernier_chargement >= SCHEDULE_RELOAD_SECONDS:
            self._charger()
        return self._schedule

    def set_schedule(self, schedule) -> None:  # pragma: no cover - exige par Celery
        self._schedule = schedule

    schedule = property(get_schedule, set_schedule)

    def sync(self) -> None:
        """Relecture forcee. Appelee par Beat a l'arret et de loin en loin.

        Ne suffit pas a rendre les changements visibles (voir `get_schedule`) :
        elle reste ici parce qu'elle ne coûte rien et evite un calendrier
        perime si le garde temporel venait a etre allonge.
        """
        self._charger()

    def _charger(self) -> None:
        # Marque le passage AVANT la requete : une base injoignable ne doit pas
        # provoquer une nouvelle tentative a chaque tick.
        self._dernier_chargement = time.monotonic()
        db = SessionLocal()
        try:
            entrees: dict[str, ScheduleEntry] = {}
            lignes = (
                db.query(ScheduledTask).filter(ScheduledTask.enabled.is_(True)).all()
            )
            for ligne in lignes:
                # ⚠️ Resolution par liste blanche : une action absente est
                # ignoree et journalisee, jamais declenchee. La base ne doit pas
                # pouvoir faire executer une tache imprevue.
                if ligne.action not in KNOWN_ACTIONS:
                    logger.warning(
                        "Planification : action inconnue ignoree (%s) sur « %s »",
                        ligne.action,
                        ligne.label,
                    )
                    continue
                try:
                    calendrier = crontab(
                        minute=ligne.cron_minute,
                        hour=ligne.cron_hour,
                        day_of_week=ligne.cron_day_of_week,
                    )
                except Exception:
                    # Un crontab invalide ne doit pas empecher les AUTRES
                    # entrees de tourner : on ecarte la ligne fautive.
                    logger.exception(
                        "Planification : horaire invalide sur « %s », entree ignoree",
                        ligne.label,
                    )
                    continue

                entrees[ligne.label] = ScheduleEntry(
                    name=ligne.label,
                    task=ligne.action,
                    schedule=calendrier,
                    options={"queue": ligne.queue},
                    app=self.app,
                )
        except Exception:
            # ⚠️ Base injoignable : on GARDE le calendrier precedent plutot que
            # de le vider. Un vidage silencieux arreterait toute la
            # planification -- collecte et alerting compris -- sur une panne
            # passagere.
            logger.exception(
                "Planification illisible : calendrier precedent conserve (%d entrees)",
                len(self._schedule),
            )
            return
        finally:
            db.close()

        if entrees != self._schedule:
            logger.info(
                "Planification rechargee : %d entree(s) active(s)", len(entrees)
            )
        self._schedule = entrees
