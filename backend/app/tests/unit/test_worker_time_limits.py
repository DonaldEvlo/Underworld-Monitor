"""Verrouille les limites de temps des taches Celery longues.

CONTRIBUTING.md §8 : une tache qui depasse `task_time_limit` est tuee puis
**rejouee** (`task_acks_late=True`) sans jamais aboutir, en remartelant la
source a chaque tentative. Le symptome est silencieux -- pas d'erreur
applicative, juste une tache qui ne finit jamais.

Ces tests comparent les limites declarees aux durees REELLEMENT mesurees en
production, pour qu'une regression (limite baissee, source devenue plus lente)
se voie au test plutot qu'en exploitation."""

from app.worker.celery_app import celery_app

# Durees mesurees sur des executions planifiees reelles.
# collect.source : 5 executions de DARKNET ARMY (XenForo), 2026-08-21.
WORST_OBSERVED_COLLECT_SECONDS = 1481
# collect.dread : cycle complet 8 subdreads + 92 corps, 2026-08-20.
WORST_OBSERVED_DREAD_SECONDS = 1433


def _limits(task_name: str) -> tuple[int, int]:
    task = celery_app.tasks[task_name]
    return task.soft_time_limit, task.time_limit


class TestCollectSourceLimits:
    def test_has_its_own_limits(self):
        """Sans limites propres, la tache herite des 30/35 min de l'app --
        insuffisant pour une source a 25 min (marge de 5 min seulement)."""
        soft, hard = _limits("collect.source")
        assert soft is not None
        assert hard is not None

    def test_soft_limit_leaves_margin_over_worst_case(self):
        soft, _ = _limits("collect.source")
        assert soft >= WORST_OBSERVED_COLLECT_SECONDS * 1.5

    def test_hard_limit_is_above_soft(self):
        """Le hard doit laisser a la tache le temps de traiter proprement
        SoftTimeLimitExceeded avant d'etre tuee."""
        soft, hard = _limits("collect.source")
        assert hard > soft


class TestDreadLimits:
    def test_soft_limit_leaves_margin_over_worst_case(self):
        soft, _ = _limits("collect.dread")
        assert soft >= WORST_OBSERVED_DREAD_SECONDS * 1.5

    def test_runs_on_dedicated_queue(self):
        """File dediee : un cycle de ~24 min sur la file par defaut bloquerait
        la collecte des autres sources ET l'alerting horaire."""
        assert celery_app.tasks["collect.dread"].queue == "dread"

    def test_hard_limit_is_above_soft(self):
        soft, hard = _limits("collect.dread")
        assert hard > soft


class TestLinkCheckLimits:
    def test_runs_on_dedicated_queue(self):
        assert celery_app.tasks["links.check_corpus"].queue == "links"

    def test_limits_cover_worst_case_pass(self):
        """Pire cas mesure d'une passe complete : ~130 min (CONTRIBUTING.md §6)."""
        soft, _ = _limits("links.check_corpus")
        assert soft >= 130 * 60


class TestCollectEtaEstimation:
    """Estimation du temps restant pendant une collecte groupee. Sans elle,
    l'interface affichait « 7/24 sources » sans dire combien de temps il
    restait."""

    def test_no_estimate_without_any_known_duration(self):
        """⚠️ `None` plutot qu'un chiffre invente : mieux vaut ne rien afficher
        qu'annoncer une duree qu'aucune mesure ne soutient."""
        from app.services.collect_batch_service import calculer_eta

        assert calculer_eta([None, None], [], 5) is None

    def test_divides_by_parallelism(self):
        """Les sources sont collectees jusqu'a 5 a la fois : une somme brute
        surestimerait d'un facteur 5."""
        from app.services.collect_batch_service import calculer_eta

        assert calculer_eta([100] * 5, [100], 5) == 100

    def test_an_untimed_source_counts_as_the_median_not_zero(self):
        """Sinon une premiere collecte annoncerait « quelques secondes » avant
        de tourner une heure."""
        from app.services.collect_batch_service import calculer_eta

        # Trois sources restantes dont deux jamais chronometrees ; mediane 600.
        assert calculer_eta([600, None, None], [600], 1) == 1800

    def test_finished_sources_are_excluded(self):
        from app.services.collect_batch_service import calculer_eta

        assert calculer_eta([], [300], 5) == 0
