import time

import redis

from aos.db.cache import get_redis
from aos.logging import get_logger

log = get_logger(__name__)


class RateLimiter:
    """Fixed one-minute windows per key, shared by every process through Redis."""

    def __init__(self, client: redis.Redis | None = None, prefix: str = "aos:ratelimit") -> None:
        self._client = client
        self._prefix = prefix

    def allow(self, key: str, limit_per_min: int) -> bool:
        if limit_per_min <= 0:
            return True
        client = self._client or get_redis()
        window_key = f"{self._prefix}:{key}:{int(time.time() // 60)}"
        try:
            pipe = client.pipeline()
            pipe.incr(window_key)
            pipe.expire(window_key, 120)
            count, _ = pipe.execute()
        except redis.RedisError as exc:
            log.warning(
                "rate limiter unavailable, allowing call", extra={"fields": {"error": str(exc)}}
            )
            return True
        return int(count) <= limit_per_min
