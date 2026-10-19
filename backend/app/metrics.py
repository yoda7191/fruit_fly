"""Prometheus metrics at /metrics.

Three kinds:
- HTTP requests: count and latency per route *template* (/api/experiments/{experiment_id},
  not each id), so the number of label combinations stays bounded.
- Events this API process sees: experiments submitted, requests refused (by reason).
- Queue state, read from the database at scrape time. In "redis" mode experiments
  run in separate worker processes, whose in-memory counters this process can't
  see; the database is the one place that knows every experiment, so gauges from
  it are correct in both modes.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from .db import ExperimentRow, utcnow

STATUSES = ("queued", "running", "done", "failed", "cancelled")


class QueueCollector:
    """Experiments by status, and how long the oldest queued one has waited."""

    def __init__(self, sessions: sessionmaker):
        self.sessions = sessions

    def collect(self):
        with self.sessions() as s:
            counts = dict(s.execute(select(ExperimentRow.status, func.count())
                                    .group_by(ExperimentRow.status)).all())
            oldest = s.scalar(select(func.min(ExperimentRow.created_at))
                              .where(ExperimentRow.status == "queued"))
        g = GaugeMetricFamily("fruit_fly_experiments", "Stored experiments by status", labels=["status"])
        for status in STATUSES:
            g.add_metric([status], counts.get(status, 0))
        yield g
        if oldest is not None and oldest.tzinfo is None:   # SQLite returns naive UTC in raw queries
            from datetime import timezone
            oldest = oldest.replace(tzinfo=timezone.utc)
        wait = (utcnow() - oldest).total_seconds() if oldest is not None else 0.0
        yield GaugeMetricFamily("fruit_fly_oldest_queued_seconds",
                                "Age of the oldest queued experiment (0 if none): a backed-up queue",
                                value=max(0.0, wait))


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter("fruit_fly_http_requests", "HTTP requests",
                                ["method", "route", "status"], registry=self.registry)
        self.latency = Histogram("fruit_fly_http_request_duration_seconds", "HTTP request latency",
                                 ["method", "route"], registry=self.registry,
                                 buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
        self.submitted = Counter("fruit_fly_experiments_submitted", "Experiments queued by this API",
                                 ["kind"], registry=self.registry)
        self.refused = Counter("fruit_fly_requests_refused", "Write requests refused",
                               ["reason"], registry=self.registry)

    def watch_database(self, sessions: sessionmaker) -> None:
        self.registry.register(QueueCollector(sessions))


class MetricsMiddleware:
    """Plain ASGI middleware: watches the response status without re-streaming the
    body (FastAPI's @app.middleware("http") does re-stream it, which made the gzip
    layer compress even tiny responses)."""

    def __init__(self, app, metrics: Metrics):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start, status = time.perf_counter(), 500

        async def send_and_record(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_record)
        finally:
            path = getattr(scope.get("route"), "path", None)
            if path is not None and path != "/metrics":    # unmatched paths would add unbounded labels
                method = scope["method"]
                self.metrics.requests.labels(method, path, str(status)).inc()
                self.metrics.latency.labels(method, path).observe(time.perf_counter() - start)


def install(app: FastAPI, metrics: Metrics) -> None:
    """Request metrics middleware and the /metrics endpoint."""
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    @app.get("/metrics", include_in_schema=False)
    def scrape() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)
