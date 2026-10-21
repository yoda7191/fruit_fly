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

import shutil
import time
from pathlib import Path

from fastapi import FastAPI, Response
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter,
                               Gauge, Histogram, PlatformCollector, ProcessCollector,
                               generate_latest)
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from .db import ExperimentRow, SweepRow, utcnow

STATUSES = ("queued", "running", "done", "failed", "cancelled")


class QueueCollector:
    """Experiments and sweeps by status, queue wait time, and storage usage."""

    def __init__(self, sessions: sessionmaker, storage_dir: Path | None = None):
        self.sessions = sessions
        self.storage_dir = storage_dir

    def collect(self):
        with self.sessions() as s:
            counts = dict(s.execute(select(ExperimentRow.status, func.count())
                                    .group_by(ExperimentRow.status)).all())
            oldest = s.scalar(select(func.min(ExperimentRow.created_at))
                              .where(ExperimentRow.status == "queued"))
            total_sweeps = s.scalar(select(func.count()).select_from(SweepRow)) or 0
            recent_finished = s.execute(
                select(ExperimentRow.started_at, ExperimentRow.finished_at)
                .where(ExperimentRow.status == "done")
                .order_by(ExperimentRow.finished_at.desc())
                .limit(10)
            ).all()

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

        yield GaugeMetricFamily("fruit_fly_sweeps_total",
                                "Total parameter sweeps stored in database",
                                value=float(total_sweeps))

        durations = [(r[1] - r[0]).total_seconds() for r in recent_finished if r[0] and r[1]]
        avg_dur = sum(durations) / len(durations) if durations else 0.0
        yield GaugeMetricFamily("fruit_fly_recent_simulation_duration_seconds",
                                "Average duration of recently finished simulations from database (s)",
                                value=float(avg_dur))

        if self.storage_dir and self.storage_dir.exists():
            try:
                usage = shutil.disk_usage(self.storage_dir)
                yield GaugeMetricFamily("fruit_fly_storage_disk_total_bytes",
                                        "Total capacity of the storage disk in bytes",
                                        value=float(usage.total))
                yield GaugeMetricFamily("fruit_fly_storage_disk_available_bytes",
                                        "Free disk space available on storage volume in bytes",
                                        value=float(usage.free))
            except Exception:
                pass


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        try:
            ProcessCollector(registry=self.registry)
            PlatformCollector(registry=self.registry)
        except Exception:
            pass

        # HTTP request metrics
        self.requests = Counter("fruit_fly_http_requests", "HTTP requests",
                                ["method", "route", "status"], registry=self.registry)
        self.latency = Histogram("fruit_fly_http_request_duration_seconds", "HTTP request latency",
                                 ["method", "route"], registry=self.registry,
                                 buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))

        # API business events
        self.submitted = Counter("fruit_fly_experiments_submitted", "Experiments queued by this API",
                                 ["kind"], registry=self.registry)
        self.refused = Counter("fruit_fly_requests_refused", "Write requests refused",
                               ["reason"], registry=self.registry)

        # Simulation & worker performance
        self.simulation_duration = Histogram(
            "fruit_fly_simulation_duration_seconds", "Simulation execution time in seconds",
            ["status"], registry=self.registry,
            buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
        )
        self.queue_wait = Histogram(
            "fruit_fly_queue_wait_duration_seconds", "Time spent waiting in queue before execution starts",
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )
        self.simulations_total = Counter(
            "fruit_fly_simulations_total", "Completed simulation runs",
            ["status"], registry=self.registry,
        )
        self.spikes_simulated = Counter(
            "fruit_fly_spikes_simulated_total", "Total action potentials simulated",
            registry=self.registry,
        )
        self.simulation_speedup = Histogram(
            "fruit_fly_simulation_speedup_ratio", "Ratio of simulated duration to wall-clock duration",
            registry=self.registry,
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0),
        )
        self.workers_busy = Gauge(
            "fruit_fly_workers_busy", "Number of simulation jobs currently executing",
            registry=self.registry,
        )
        self.sse_connections = Gauge(
            "fruit_fly_sse_connections_active", "Active Server-Sent Events streaming connections",
            registry=self.registry,
        )

    def watch_database(self, sessions: sessionmaker, storage_dir: Path | None = None) -> None:
        self.registry.register(QueueCollector(sessions, storage_dir=storage_dir))


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
