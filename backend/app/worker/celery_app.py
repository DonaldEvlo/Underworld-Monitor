"""Application Celery : collecte et alerting planifies.

Jusqu'ici toute la chaine tournait a la demande (un clic dans l'UI), ce qui
avait trois consequences concretes : aucune alerte ne se generait sans action
humaine, tous les documents portaient la meme date de collecte (impossible de
montrer une tendance a un RSSI), et rien ne prouvait la fraicheur du corpus.
Ce module comble ce manque.

Le worker partage le code metier de l'API -- les taches (worker/tasks/) sont
des wrappers fins autour de services/ et pipeline/, conformement a
CONTRIBUTING.md §3.3. Rien de ce qui est ici ne doit contenir de logique metier.

Reseaux : le worker a besoin de `app_net` (db, redis) ET `collect_net` (Tor),
comme le backend -- voir docker-compose.yml."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "threat_intel",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.worker.tasks.collect_tasks",
        "app.worker.tasks.alert_tasks",
        "app.worker.tasks.link_tasks",
        "app.worker.tasks.dread_tasks",
        "app.worker.tasks.address_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Une tache de collecte peut etre longue (Tor + delais de politesse sur
    # plusieurs sources) : sans limite, un collecteur bloque immobiliserait un
    # worker indefiniment.
    task_soft_time_limit=30 * 60,
    task_time_limit=35 * 60,
    # Un worker ne prend qu'une tache a la fois : la collecte est deja
    # parallelisee en interne (ThreadPoolExecutor cote API) et sature surtout
    # le circuit Tor -- empiler les taches n'accelererait rien et multiplierait
    # les requetes simultanees vers les memes sources, contraire aux delais de
    # politesse (voir pipeline/collect/politeness.py).
    worker_prefetch_multiplier=1,
    # Accuse reception apres execution : si le worker meurt en cours de
    # collecte, la tache est rejouee plutot que perdue silencieusement.
    task_acks_late=True,
    # Comportement par defaut a partir de Celery 6 (sans ce reglage explicite,
    # un avertissement de depreciation est emis a chaque demarrage) : reessayer
    # la connexion au broker au demarrage, utile quand le worker demarre avant
    # que Redis soit pret.
    broker_connection_retry_on_startup=True,
)

# Imports a effet de bord, apres la creation de l'app :
# - les modules de taches enregistrent leurs @celery_app.task. `include`
#   ci-dessus suffit au worker, mais pas a un import direct de ce module
#   (l'API, un test, un shell) : sans ces lignes, `celery_app.tasks` y est vide
#   et `.delay()` echouerait a la premiere utilisation depuis l'API.
# - schedules.py n'expose plus de calendrier statique : il amorce seulement
#   les entrees par defaut sur une base vierge. Le calendrier reel vit en
#   base et est lu par worker/db_scheduler.DatabaseScheduler.
from app.worker.tasks import (  # noqa: E402,F401
    address_tasks,
    alert_tasks,
    collect_tasks,
    dread_tasks,
    link_tasks,
)
from app.worker import schedules  # noqa: E402,F401

# Alias d'hôtes des sources déménagées : sans eux, une source dont l'adresse a
# basculé retomberait sur le collecteur générique (voir host_aliases.py).
from app.services.source_address_service import installer_alias  # noqa: E402

installer_alias()

# ⚠️ Ordonnanceur alimente par la BASE : les horaires se gerent depuis
# l'interface, sans recreer le service `beat`.
from app.worker.db_scheduler import SCHEDULE_RELOAD_SECONDS  # noqa: E402

celery_app.conf.beat_scheduler = "app.worker.db_scheduler:DatabaseScheduler"
# Intervalle de boucle de Beat. Par defaut 300 s : un horaire modifie depuis
# l'interface aurait mis jusqu'a 5 minutes a prendre effet, alors que
# l'interface annonce une minute. Les deux valeurs doivent rester la meme.
celery_app.conf.beat_max_loop_interval = SCHEDULE_RELOAD_SECONDS
