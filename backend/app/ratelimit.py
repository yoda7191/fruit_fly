"""Per-client rate limits on experiment submissions.

A client (an API key, or the client address when keys aren't required) may start
at most `limit` experiments per minute; a sweep costs one per experiment it
creates. Fixed one-minute windows: simple, and cheap enough to check on every
submission. This is separate from FRUIT_FLY_MAX_PENDING, which protects the
server as a whole; the rate limit stops one client from taking all of it.

MemoryRateLimiter suits a single API process (FRUIT_FLY_QUEUE=thread).
RedisRateLimiter shares counts between processes: INCRBY and EXPIRE run in one
MULTI/EXEC transaction, so concurrent requests can't both slip under the limit.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Protocol

WINDOW_S = 60


class RateLimited(Exception):
    def __init__(self, retry_after: int, message: str):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter(Protocol):
    def charge(self, client: str, cost: int) -> None:
        """Count `cost` experiments for `client`, or raise RateLimited."""


def _window(now: float) -> tuple[int, int]:
    """(window number, seconds until it ends)."""
    w = int(now // WINDOW_S)
    return w, max(1, math.ceil((w + 1) * WINDOW_S - now))


def _check(client: str, cost: int, limit: int, used_before: int, retry_after: int) -> None:
    if cost > limit:
        raise RateLimited(retry_after, f"this request starts {cost} experiments; the limit is {limit} "
                                       f"per minute per client")
    if used_before + cost > limit:
        raise RateLimited(retry_after, f"rate limit: {limit} experiments per minute per client; "
                                       f"{used_before} already started this minute")


class NoRateLimit:
    def charge(self, client: str, cost: int) -> None:
        return None


class MemoryRateLimiter:
    def __init__(self, limit: int, clock=time.time):
        self.limit = limit
        self.clock = clock
        self._lock = threading.Lock()
        self._used: dict[str, tuple[int, int]] = {}      # client -> (window, experiments)

    def charge(self, client: str, cost: int) -> None:
        window, retry = _window(self.clock())
        with self._lock:
            w, used = self._used.get(client, (window, 0))
            used = used if w == window else 0
            _check(client, cost, self.limit, used, retry)
            self._used[client] = (window, used + cost)
            if len(self._used) > 10_000:                  # forget old clients
                self._used = {c: v for c, v in self._used.items() if v[0] == window}


class RedisRateLimiter:
    def __init__(self, redis_url: str, limit: int, clock=time.time, prefix: str = "fruit_fly:rate"):
        import redis
        self.redis = redis.Redis.from_url(redis_url)
        self.limit = limit
        self.clock = clock
        self.prefix = prefix

    def charge(self, client: str, cost: int) -> None:
        window, retry = _window(self.clock())
        key = f"{self.prefix}:{client}:{window}"
        if cost > self.limit:
            _check(client, cost, self.limit, 0, retry)
        pipe = self.redis.pipeline()                      # MULTI/EXEC: atomic
        pipe.incrby(key, cost)
        pipe.expire(key, WINDOW_S * 2)
        total, _ = pipe.execute()
        if total > self.limit:
            self.redis.decrby(key, cost)                  # refused requests don't count
            _check(client, cost, self.limit, total - cost, retry)


def make_rate_limiter(limit: int, queue: str, redis_url: str) -> RateLimiter:
    if limit <= 0:
        return NoRateLimit()
    return RedisRateLimiter(redis_url, limit) if queue == "redis" else MemoryRateLimiter(limit)
