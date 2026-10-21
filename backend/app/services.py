"""Build the database, spike store and job service from settings.
Shared by the API (main.py) and the worker process (worker.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine

from .config import Settings
from .db import init_db, make_engine, make_sessionmaker
from .jobs import JobService
from .model import ModelStore
from .runner import run_experiment
from .spikes import make_spike_store

if TYPE_CHECKING:
    from .metrics import Metrics


def create_job_service(settings: Settings, store: ModelStore | None,
                       metrics: Metrics | None = None) -> tuple[JobService, Engine]:
    """store=None: the service can submit and read experiments but not run them."""
    engine = make_engine(settings.db_url)
    init_db(engine)
    spikes = make_spike_store(settings)
    if hasattr(spikes, "check"):
        spikes.check()                                  # e.g. a missing S3 bucket: fail now
    service = JobService(
        make_sessionmaker(engine),
        spikes,
        max_pending=settings.max_pending,
        max_experiments=settings.max_experiments,
        run=(lambda req, progress: run_experiment(store, req, progress)) if store else None,
        metrics=metrics,
    )
    return service, engine