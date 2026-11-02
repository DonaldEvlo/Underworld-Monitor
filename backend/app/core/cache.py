import redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Client Redis partagé — stockage temporaire uniquement (pages collectées en
    batch, TTL). Jamais de données persistantes : Postgres reste la seule source
    de vérité durable."""
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client
