from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    API_ENV: str = "development"
    API_CORS_ORIGINS: str = "http://localhost:5173"

    JWT_SECRET_KEY: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    # Jeton d'accès court (10 min) : client.ts le rafraîchit seul. La vraie
    # limite d'une session est côté serveur (SESSION_*, ci-dessous) : un
    # jeton n'est accepté que si sa session vit encore.
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Sessions côté serveur (migration 0035). Une session meurt après
    # SESSION_IDLE_TIMEOUT_MINUTES sans requête authentifiée (onglet fermé,
    # poste en veille), et au plus tard SESSION_MAX_HOURS après la connexion.
    # ⚠️ Aligné sur le délai d'inactivité du navigateur (IDLE_TIMEOUT_MS,
    # frontend/src/hooks/useIdleTimeout.ts) : l'interface déconnecte après
    # 10 min sans geste de l'utilisateur, le serveur après 10 min sans
    # requête. Le navigateur envoie un signal d'activité tant que
    # l'utilisateur agit, même sans appeler l'API.
    SESSION_IDLE_TIMEOUT_MINUTES: int = 10
    SESSION_MAX_HOURS: int = 12

    DATABASE_URL: str = "postgresql+psycopg://tip_user:changeme@db:5432/threat_intel"
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"

    # Planification du worker (voir worker/schedules.py). Format crontab :
    # "6,18" = 06:00 et 18:00 UTC. Surchargeables pour accelerer en
    # demonstration sans toucher au code (ex: ALERT_SCHEDULE_MINUTE="*/5").
    COLLECT_SCHEDULE_HOURS: str = "6,18"
    COLLECT_SCHEDULE_MINUTE: str = "17"
    ALERT_SCHEDULE_MINUTE: str = "7"

    # Continents surveilles pour les alertes de perimetre GEOGRAPHIQUE (voir
    # services/alert_service.py, migration 0016). Vide = aucune alerte
    # regionale, seules les entites declarees alertent.
    #
    # Defaut "Afrique" : c'est le perimetre du produit. Mesure du 2026-09-02 --
    # 20 domaines de victimes africaines issus de sites de fuite, dont 18 deja
    # surveilles ; les 2 restants (suivi-flotte.co.za, mutuelle-exemple.co.zw) sont de
    # vraies victimes que rien ne signalait.
    ALERT_WATCHED_CONTINENTS: str = "Afrique"

    # Modele employe pour l'ARBITRAGE des annonces `uncertain`, distinct de
    # celui que l'analyste choisit pour le chat.
    #
    # Banc d'essai du 2026-09-03 sur 30 cas a verite terrain (sites de fuite ->
    # `leak`, annonces franchement hors perimetre -> `noise`) :
    #   llama3   temperature defaut : 16/30 (53 %) en 48 s
    #   llama3   temperature 0      : 18/30 (60 %) en 20 s
    #   qwen3:8b temperature defaut : 27/30 (90 %) en 206 s
    #   qwen3:8b temperature 0      : 27/30 (90 %) en 138 s
    #
    # qwen3 est ~7x plus lent mais passe de 60 % a 90 % de justesse : sur une
    # tache de classification en batch, la justesse prime sur la latence.
    # ⚠️ Exige `ollama pull qwen3:8b`. A defaut, l'appel echoue lot par lot et
    # les documents restent simplement sans verdict (voir le service).
    TRIAGE_LLM_MODEL: str = "ollama:qwen3:8b"

    # ⚠️ Temperature NULLE pour toute classification. La docstring de
    # `generate_response` le demandait deja ; l'avoir laissee au defaut
    # expliquait l'instabilite de format du modele (numerotation en double,
    # preambules) et une partie des decalages. Mesure : aucune perte de
    # justesse, et 33 a 60 % de temps gagne.
    TRIAGE_LLM_TEMPERATURE: float = 0.0

    # Temperature des taches de RESTITUTION FACTUELLE (resume d'alerte,
    # synthese globale). Meme raison que pour l'arbitrage : ces textes doivent
    # rapporter des donnees fournies, pas en produire.
    #
    # ⚠️ Le defaut du modele avait un cout mesurable : la synthese globale a
    # annonce « seule Organisation Exemple a ete verifiee par un observateur tiers »,
    # exactement l'inverse de la realite, et a invente des decomptes par pays.
    SUMMARY_LLM_TEMPERATURE: float = 0.0
    # Verification de vivacite des liens (voir worker/tasks/link_tasks.py) :
    # une fois par jour, decalee de la collecte -- cette tache emet du trafic
    # Tor vers des hotes tiers, contrairement a l'alerting.
    LINK_CHECK_SCHEDULE_HOUR: str = "9"
    LINK_CHECK_SCHEDULE_MINUTE: str = "37"
    # Collecte Dread (voir worker/tasks/dread_tasks.py) : file dediee, ~25 min
    # par cycle. Creneau volontairement isole des autres taches Tor (collecte
    # 6h/18h, liens 9h37) pour ne pas concentrer le trafic sortant.
    DREAD_COLLECT_SCHEDULE_HOUR: str = "13"
    DREAD_COLLECT_SCHEDULE_MINUTE: str = "23"

    # Poivre du HMAC-SHA256 applique aux mots de passe detectes (voir
    # pipeline/detect/masking.py::hash_password). Vit HORS de la base : un
    # attaquant qui obtiendrait un dump de `detections` ne peut pas monter
    # d'attaque par dictionnaire sans cette valeur -- c'est tout l'interet par
    # rapport a un SHA-256 nu, reversible en pratique sur un mot de passe
    # (entropie faible). Doit etre genere aleatoirement en production et ne
    # jamais changer ensuite (le changer rend les hash existants incomparables).
    PASSWORD_HASH_PEPPER: str = ""

    TOR_SOCKS_HOST: str = "tor"
    TOR_SOCKS_PORT: int = 9050
    TOR_CONTROL_HOST: str = "tor"
    TOR_CONTROL_PORT: int = 9051
    TOR_CONTROL_PASSWORD: str = "changeme"

    # Client API Telegram (MTProto), lecture seule des canaux publics -- voir
    # pipeline/collect/telegram/mtproto_client.py. Vides = collecte par
    # l'apercu web (t.me/s/), sans compte. La session est un SECRET (elle vaut
    # le compte) : un volume Docker, jamais le depot. Telethon ajoute
    # `.session` au chemin. `TELEGRAM_API_ID` est une CHAINE : une ligne vide
    # dans .env (`TELEGRAM_API_ID=`) ferait echouer un `int | None` au
    # demarrage de TOUTE l'application ; la conversion se fait a l'usage.
    TELEGRAM_API_ID: str = ""
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_SESSION_PATH: str = "/telegram-session/collector"

    OPENAI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    INTELX_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    LLM_MODEL: str = "gpt-4.1-mini"

    TRANSLATION_MODELS_DIR: str = "/app/translation_models"

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.API_CORS_ORIGINS.split(",")
            if origin.strip()
        ]


_SECRETS_PAR_DEFAUT = frozenset({"", "changeme"})


def verifier_secrets(s: "Settings") -> None:
    """Refuse de démarrer l'API avec une clé de signature des jetons vide ou
    laissée à sa valeur d'exemple (audit du 2026-10-06).

    ⚠️ Avec `JWT_SECRET_KEY=changeme` (valeur par défaut de ce fichier et de
    `.env.example`), n'importe qui peut fabriquer un jeton valide pour
    n'importe quel compte, administrateur compris. Un `.env` absent ou
    incomplet ne doit jamais produire une API ouverte en silence."""
    if s.JWT_SECRET_KEY in _SECRETS_PAR_DEFAUT:
        raise RuntimeError(
            "JWT_SECRET_KEY est vide ou vaut « changeme » : définissez une valeur "
            "aléatoire dans .env (par exemple : openssl rand -hex 32)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
