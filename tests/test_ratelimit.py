import fakeredis
import pytest
import redis

from app.api.ratelimit import RateLimiter, RateLimitExceeded


def test_blocks_after_limit():
    rl = RateLimiter(fakeredis.FakeRedis(), limit_per_minute=3)
    for _ in range(3):
        rl.check("u")
    with pytest.raises(RateLimitExceeded):
        rl.check("u")


def test_limits_are_per_user():
    rl = RateLimiter(fakeredis.FakeRedis(), limit_per_minute=1)
    rl.check("a")
    rl.check("b")  # different user, still allowed


def test_fails_open_without_redis():
    RateLimiter(None, 1).check("u")


def test_fails_open_on_redis_error():
    class Broken:
        def incr(self, *_):
            raise redis.ConnectionError("down")

    RateLimiter(Broken(), 1).check("u")  # must not raise
