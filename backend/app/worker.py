"""Worker process for FRUIT_FLY_QUEUE=redis.

    python -m backend.app.worker        (same FRUIT_FLY_* settings as the API)

Loads the circuit once, then runs experiments from the Redis queue one at a
time. Start several workers (on one or more machines) to run experiments in
parallel; they coordinate only through Redis and the database.
"""

from __future__ import annotations

import logging
import os
import socket

from . import logs
from .config import Settings
from .events import RedisBus
from .jobs import JobService, RedisQueue
from .model import ModelStore
from .services import create_job_service

log = logging.getLogger("fruit_fly.worker")
_service: JobService | None = None


def _get_service() -> JobService:
    global _service
    if _service is None:                      # e.g. a worker started with plain `rq worker`
        settings = Settings.from_env()
        _service, _ = create_job_service(settings, ModelStore(settings))
        _service.events = RedisBus(settings.redis_url)
    return _service


def run_job(experiment_id: str) -> None:
    """Entry point RQ calls for every queued experiment."""
    _get_service().execute(experiment_id)


def main() -> None:
    from rq import Queue, SimpleWorker

    settings = Settings.from_env()
    logs.configure(settings.log_format, settings.log_level)
    log.info("loading circuit from %s", settings.circuit_dir)
    store = ModelStore(settings)
    service, _ = create_job_service(settings, store)
    service.events = RedisBus(settings.redis_url)          # live progress for the API's streams
    stale = service.fail_stale(settings.job_timeout_s)
    if stale:
        log.warning("marked %d experiments failed: still running after %d s (a worker had stopped)",
                    stale, settings.job_timeout_s)

    # RQ imports this module by name ("backend.app.worker"); when started with
    # `python -m` we are "__main__", so hand the loaded service to that module.
    from backend.app import worker as named_module
    named_module._service = service

    queue = RedisQueue(settings.redis_url, settings.job_timeout_s)
    # SimpleWorker runs jobs in this process, so the circuit is loaded only once.
    worker = SimpleWorker([Queue(RedisQueue.NAME, connection=queue.connection)],
                          connection=queue.connection,
                          name=f"fruit-fly-{socket.gethostname()}-{os.getpid()}")
    log.info("worker %s waiting for experiments on %s", worker.name, settings.redis_url)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()