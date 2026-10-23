import fakeredis
import redis

from aos.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        if settings.storage_mode == "memory":
            _client = fakeredis.FakeRedis(decode_responses=True)
        else:
            _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def reset_redis() -> None:
    global _client
    _client = None
