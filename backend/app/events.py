"""Change notifications for live progress (server-sent events).

Whoever changes an experiment (a worker thread, a worker process, the API on
cancel) calls `publish(experiment_id)` and, for sweep members, the sweep's id.
A notification carries no data: it only wakes the streams watching that id,
which then re-read the row from the database. The database stays the single
source of truth, so a lost or duplicated notification can only delay an
update, never show a wrong one; streams also re-read on a timeout in case a
notification was lost (e.g. a worker died).

- LocalBus: everything in one process ("thread" queue).
- RedisBus: workers in other processes publish on a Redis channel per id.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

log = logging.getLogger("fruit_fly.events")

CHANNEL = "fruit_fly:changed:"


class Subscription(Protocol):
    async def wait(self, timeout: float) -> bool:
        """True if notified since the last wait, False on timeout."""
        ...


class EventBus(Protocol):
    def publish(self, *ids: str | None) -> None: ...
    def subscribe(self, id_: str) -> "asynccontextmanager[Subscription]": ...
    def close(self) -> None: ...


class _EventSubscription:
    def __init__(self) -> None:
        self.event = asyncio.Event()

    async def wait(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except TimeoutError:
            return False
        self.event.clear()
        return True


class LocalBus:
    """In-process: publish() may be called from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, _EventSubscription]]] = defaultdict(set)

    def publish(self, *ids: str | None) -> None:
        with self._lock:
            targets = [t for i in ids if i for t in self._subs.get(i, ())]
        for loop, sub in targets:
            try:
                loop.call_soon_threadsafe(sub.event.set)
            except RuntimeError:                 # that loop has closed
                pass

    @asynccontextmanager
    async def subscribe(self, id_: str) -> AsyncIterator[_EventSubscription]:
        entry = (asyncio.get_running_loop(), _EventSubscription())
        with self._lock:
            self._subs[id_].add(entry)
        try:
            yield entry[1]
        finally:
            with self._lock:
                self._subs[id_].discard(entry)
                if not self._subs[id_]:
                    del self._subs[id_]

    def close(self) -> None:
        pass


class _RedisSubscription:
    def __init__(self, pubsub) -> None:
        self.pubsub = pubsub

    async def wait(self, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (left := deadline - loop.time()) > 0:
            msg = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=left)
            if msg is not None:
                while await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0):
                    pass                         # coalesce a burst into one wake-up
                return True
        return False


class RedisBus:
    """Across processes. publish() is synchronous (worker code is), subscribe()
    uses redis.asyncio so a waiting stream doesn't hold a thread."""

    def __init__(self, redis_url: str) -> None:
        from redis import Redis
        self.url = redis_url
        self._redis = Redis.from_url(redis_url)
        self._async = None

    def publish(self, *ids: str | None) -> None:
        try:
            for i in ids:
                if i:
                    self._redis.publish(CHANNEL + i, b"1")
        except Exception:                        # progress display must never fail a job
            log.warning("could not publish a change notification", exc_info=True)

    @asynccontextmanager
    async def subscribe(self, id_: str) -> AsyncIterator[_RedisSubscription]:
        if self._async is None:
            from redis.asyncio import Redis as AsyncRedis
            self._async = AsyncRedis.from_url(self.url)
        pubsub = self._async.pubsub()
        await pubsub.subscribe(CHANNEL + id_)
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    def close(self) -> None:
        self._redis.close()


class NullBus:
    """For a worker process that has no Redis configured (tests)."""

    def publish(self, *ids: str | None) -> None:
        pass

    def close(self) -> None:
        pass


# ====================================================================== streams

KEEPALIVE_S = 15.0


def sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def stream_changes(request, bus: EventBus, id_: str, read, *,
                         min_interval_s: float = 0.0) -> AsyncIterator[str]:
    """Server-sent events for one experiment or sweep.

    `read()` is a blocking function returning (json, finished), or None if the
    item no longer exists. Sends `update` whenever the JSON changes, then `end`
    once finished (so the browser's EventSource doesn't reconnect), or `gone`.
    Subscribes before the first read, so no change between the two is missed.
    """
    from starlette.concurrency import run_in_threadpool

    metrics = getattr(getattr(request, "app", None), "state", None)
    metrics_obj = getattr(metrics, "metrics", None) if metrics else None
    if metrics_obj and hasattr(metrics_obj, "sse_connections"):
        metrics_obj.sse_connections.inc()

    try:
        async with bus.subscribe(id_) as sub:
            last = None
            while True:
                state = await run_in_threadpool(read)
                if state is None:
                    yield sse("gone", "{}")
                    return
                data, finished = state
                if data != last:
                    yield sse("update", data)
                    last = data
                if finished:
                    yield sse("end", "{}")
                    return
                if not await sub.wait(KEEPALIVE_S):
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"          # comment line: keeps proxies from closing the stream
                elif min_interval_s:
                    await asyncio.sleep(min_interval_s)   # coalesce bursts (a sweep's many members)
    finally:
        if metrics_obj and hasattr(metrics_obj, "sse_connections"):
            metrics_obj.sse_connections.dec()
