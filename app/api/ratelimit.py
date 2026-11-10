"""Per-user fixed-window rate limiter backed by Redis.

Fails open if Redis is unavailable, but a real "limit exceeded" decision is never
swallowed (the original VietBot caught its own 429 in a broad `except`).
"""
import logging

import redis

log = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(self, client: "redis.Redis | None", limit_per_minute: int = 10):
        self.client = client
        self.limit = limit_per_minute

    def check(self, user_key: str) -> None:
        """Raise RateLimitExceeded if the user is over the limit."""
        if self.client is None:
            return
        key = f"rate_limit:{user_key}"
        try:
            count = self.client.incr(key)
            if count == 1:
                self.client.expire(key, 60)
        except redis.RedisError as exc:  # infrastructure failure -> fail open
            log.error("Redis failed during rate limit check: %s", exc)
            return
        if count > self.limit:
            raise RateLimitExceeded()


def connect_redis(host: str, port: int) -> "redis.Redis | None":
    try:
        client = redis.Redis(host=host, port=port, db=0, socket_connect_timeout=1)
        client.ping()
        log.info("Redis connected.")
        return client
    except (redis.ConnectionError, redis.TimeoutError):
        log.warning("Redis is down. Rate limiting and caching are DISABLED.")
        return None
