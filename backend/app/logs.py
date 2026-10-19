"""Logging: plain text or one JSON object per line, with request and experiment ids.

Every HTTP request gets an id (the client's X-Request-ID if it sent a sensible
one, otherwise a new one), returned in the X-Request-ID response header and
attached to every log line written while handling it. The id is stored with
each experiment, and a worker running the experiment sets it again, so one id
follows a job from the API request that queued it to the worker that ran it,
even in another process:

    {"time": "...", "level": "INFO", "logger": "fruit_fly.jobs",
     "message": "experiment finished", "request_id": "3f2a...", "experiment_id": "9c1e..."}
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
experiment_id: ContextVar[str | None] = ContextVar("experiment_id", default=None)

_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")     # anything else is replaced, not logged
_HANDLER_NAME = "fruit_fly"

access_log = logging.getLogger("fruit_fly.access")


class ContextFilter(logging.Filter):
    """Copies the current request and experiment ids onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        record.experiment_id = experiment_id.get()
        return True


class JsonFormatter(logging.Formatter):
    # Fields passed with `extra=` that belong in the JSON object.
    EXTRA = ("method", "path", "route", "status", "duration_ms", "client", "forwarded_for")

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "experiment_id", *self.EXTRA):
            value = getattr(record, key, None)
            if value is not None:
                out[key] = value
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(name)s %(levelname)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        ids = [f"{k}={v[:8]}" for k in ("request_id", "experiment_id") if (v := getattr(record, k, None))]
        return f"{line} [{' '.join(ids)}]" if ids else line


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever sys.stderr is at the time (test runners swap it)."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure(fmt: str = "text", level: str = "INFO") -> None:
    """Send the fruit_fly.* loggers to stderr in the given format. Idempotent:
    calling it again (a second app in tests, a reload) replaces the handler."""
    logger = logging.getLogger("fruit_fly")
    for h in [h for h in logger.handlers if h.get_name() == _HANDLER_NAME]:
        logger.removeHandler(h)
    handler = _StderrHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False                      # don't print twice through uvicorn's root handler


def new_request_id(offered: str | None) -> str:
    return offered if offered and _VALID_ID.match(offered) else uuid.uuid4().hex


@contextmanager
def experiment_context(exp_id: str, req_id: str | None):
    """Log lines inside carry this experiment's id and its submitting request's id."""
    t1, t2 = experiment_id.set(exp_id), request_id.set(req_id)
    try:
        yield
    finally:
        experiment_id.reset(t1)
        request_id.reset(t2)


class RequestIdMiddleware:
    """Plain ASGI middleware: assigns the request id, echoes it in the response,
    and writes one access-log line per request (route template, status, time)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        offered = headers.get(b"x-request-id", b"").decode("latin-1") or None
        rid = new_request_id(offered)
        token = request_id.set(rid)
        start, status = time.perf_counter(), 500

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            route = getattr(scope.get("route"), "path", None)
            if route not in ("/metrics", "/{path:path}"):          # not scrapes or web-app files
                client = scope.get("client")
                access_log.info("%s %s %d", scope["method"], scope["path"], status, extra={
                    "method": scope["method"], "path": scope["path"], "route": route, "status": status,
                    "duration_ms": round(1000 * (time.perf_counter() - start), 1),
                    "client": client[0] if client else None,
                    # as received: behind a proxy, the visitor is one of these entries (FRUIT_FLY_PROXY_HOPS)
                    "forwarded_for": headers.get(b"x-forwarded-for", b"").decode("latin-1") or None})
            request_id.reset(token)
