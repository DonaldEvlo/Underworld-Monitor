"""Planification editable : liste blanche d'actions et validation des horaires.

Ces tests portent sur les garde-fous, pas sur le confort : une action libre
serait de l'execution de code a distance derriere un formulaire, et un horaire
invalide ecarterait silencieusement une entree du calendrier.
"""

import pytest

from app.services.scheduled_task_service import (
    KNOWN_ACTIONS,
    ScheduleError,
    describe_schedule,
    validate_action,
    validate_cron,
)


class _TacheFactice:
    """Juste les champs que `describe_schedule` lit -- pas de base ici."""

    def __init__(self, minute: str, heure: str, jours: str = "*"):
        self.cron_minute = minute
        self.cron_hour = heure
        self.cron_day_of_week = jours


class TestListeBlancheActions:
    def test_action_prevue_acceptee(self):
        for action in KNOWN_ACTIONS:
            validate_action(action)

    @pytest.mark.parametrize(
        "action",
        [
            # Une tache reelle du projet, mais NON prevue pour la planification.
            "collect.source",
            # Une tache Celery interne : l'accepter donnerait a un utilisateur
            # authentifie le moyen de faire executer n'importe quoi au worker.
            "celery.backend_cleanup",
            "",
            "collect.all_active_sources ",
        ],
    )
    def test_action_hors_liste_refusee(self, action):
        with pytest.raises(ScheduleError):
            validate_action(action)

    def test_chaque_action_impose_sa_file(self):
        """La file n'est jamais choisie par l'utilisateur.

        ⚠️ Une tache longue placee sur la file par defaut bloquerait la
        collecte ET l'alerting horaire (CONTRIBUTING.md §8) : la file est une
        propriete de l'action, pas un reglage.
        """
        assert KNOWN_ACTIONS["collect.dread"]["queue"] == "dread"
        assert KNOWN_ACTIONS["links.check_corpus"]["queue"] == "links"
        assert KNOWN_ACTIONS["alerts.generate"]["queue"] == "celery"


class TestValidationHoraire:
    @pytest.mark.parametrize(
        "minute,heure,jours",
        [
            ("0", "*", "*"),
            ("37", "9", "*"),
            ("0", "6,18", "*"),
            ("0", "*/4", "1-5"),
            ("0", "13", "0,6"),
        ],
    )
    def test_formes_celery_acceptees(self, minute, heure, jours):
        validate_cron(minute, heure, jours)

    @pytest.mark.parametrize(
        "minute,heure,jours",
        [
            # Vide : Celery accepterait "" comme faux et declencherait a des
            # moments imprevus.
            ("", "6", "*"),
            # Une expression fantaisiste passerait le crontab en exception dans
            # l'ordonnanceur, qui ecarterait l'entree SANS que l'utilisateur le
            # sache. On refuse a l'ecriture, la ou il peut corriger.
            ("0", "tous les matins", "*"),
            ("0", "6;18", "*"),
            ("0", "6", "lundi"),
        ],
    )
    def test_horaire_invalide_refuse(self, minute, heure, jours):
        with pytest.raises(ScheduleError):
            validate_cron(minute, heure, jours)


class TestBornes:
    """Ce que l'expression reguliere laisse passer mais que Celery refuse.

    ⚠️ Sans ces bornes, l'entree serait acceptee puis ECARTEE au chargement du
    calendrier : la collecte ne se declencherait jamais, sans que rien ne le
    signale a l'analyste.
    """

    @pytest.mark.parametrize(
        "minute,heure,jours",
        [
            ("60", "6", "*"),
            ("0", "24", "*"),
            ("0", "6", "7"),
            ("0", "6", "1,9"),
            ("0", "0-25", "*"),
        ],
    )
    def test_hors_bornes_refuse(self, minute, heure, jours):
        with pytest.raises(ScheduleError):
            validate_cron(minute, heure, jours)

    def test_bornes_extremes_acceptees(self):
        validate_cron("59", "23", "0")
        validate_cron("0", "0", "6")


class TestLibelleHoraire:
    def test_heure_etoile_dit_toutes_les_heures(self):
        """« a * h 7 » ne veut rien dire pour un analyste."""
        assert describe_schedule(_TacheFactice("7", "*")) == (
            "toutes les heures a la minute 7"
        )

    def test_heures_multiples_ecrites_en_passages(self):
        # « a 6,18 h 17 » se lit mal : on veut les heures reelles.
        assert describe_schedule(_TacheFactice("17", "6,18")) == "a 06:17 et 18:17"

    def test_pas_toutes_les_n_heures(self):
        assert describe_schedule(_TacheFactice("5", "*/4")) == (
            "toutes les 4 heures, a la minute 5"
        )

    @pytest.mark.parametrize(
        "champ,attendu",
        [
            ("1-5", "du lundi au vendredi"),
            ("0,6", "le week-end"),
            ("3", "le mercredi"),
            ("1,3,5", "les lundi, mercredi, vendredi"),
        ],
    )
    def test_jours_nommes_pas_numerotes(self, champ, attendu):
        assert attendu in describe_schedule(_TacheFactice("0", "9", champ))

    def test_tous_les_jours_non_repete(self):
        # « jours * » est du bruit : tous les jours est le cas normal.
        assert "jour" not in describe_schedule(_TacheFactice("0", "9", "*"))
        # Les 7 jours coches valent « tous les jours » : ne pas les enumerer.
        assert "jour" not in describe_schedule(_TacheFactice("0", "9", "0,1,2,3,4,5,6"))
