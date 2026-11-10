"""Per-key fixed-window rate limiter backed by Redis, with an in-process fallback.

Without Redis (common on a free single-instance deploy) counts are kept in this process, so a
public demo is still protected. If Redis is configured but errors, the check fails open, but a
real "limit exceeded" decision is never swallowed (the original VietBot caught its own 429 in a
broad `except`).
"""
import logging
import threading
import time

import redis

log = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(self, client: "redis.Redis | None", limit_per_minute: int = 10):
        self.client = client
        self.limit = limit_per_minute
        self._local: dict[str, tuple[int, float]] = {}  # key -> (count, window end)
        self._lock = threading.Lock()

    def _count_local(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, ends = self._local.get(key, (0, 0.0))
            if now >= ends:
                count, ends = 0, now + window
            self._local[key] = (count + 1, ends)
            if len(self._local) > 50_000:  # drop expired windows so memory stays bounded
                self._local = {k: v for k, v in self._local.items() if v[1] > now}
            return count + 1

    def check(self, user_key: str, limit: int | None = None, window: int = 60) -> None:
        """Raise RateLimitExceeded if `user_key` made more than `limit` calls in `window` s."""
        limit = self.limit if limit is None else limit
        key = f"rate_limit:{window}:{user_key}"
        if self.client is None:
            count = self._count_local(key, window)
        else:
            try:
                count = self.client.incr(key)
                if count == 1:
                    self.client.expire(key, window)
            except redis.RedisError as exc:  # infrastructure failure -> fail open
                log.error("Redis failed during rate limit check: %s", exc)
                return
        if count > limit:
            raise RateLimitExceeded()


def connect_redis(host: str, port: int) -> "redis.Redis | None":
    try:
        client = redis.Redis(host=host, port=port, db=0, socket_connect_timeout=1)
        client.ping()
        log.info("Redis connected.")
        return client
    except (redis.ConnectionError, redis.TimeoutError):
        log.warning("Redis is down. Caching is disabled; rate limits are kept in memory.")
        return None
