"""Experiment jobs: stored in the database, executed through a queue.

Life of an experiment:

    submit()   -> database row, status "queued" -> queue.enqueue(id)
                  (or the stored experiment, if an identical request already ran)
    execute()  -> runs in a worker thread ("thread" queue) or a worker process
                  ("redis" queue): status "running", progress updates, spikes
                  to disk, result to the row, status "done" or "failed"
    cancel()   -> queued: "cancelled" at once; running: flagged, and the worker
                  stops at the next odour presentation ("cancelled")

Every change is announced on the event bus (events.py) so live-progress
streams can update without polling.

The API process and worker processes share nothing but the database, the
spike folder and (for the "redis" queue) Redis, so any of them can restart
without losing finished experiments.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import sessionmaker

from .db import FINISHED, PENDING, ExperimentRow, SweepRow, utcnow
from .events import EventBus, NullBus
from .logs import experiment_context
from .runner import ProgressFn, RunOutput
from .schemas import ConditioningRequest
from .spikes import LocalSpikeStore, S3SpikeStore

log = logging.getLogger("fruit_fly.jobs")

RunFn = Callable[[ConditioningRequest, ProgressFn], RunOutput]


class CapacityError(RuntimeError):
    """Too many experiments are queued or running."""


class QueueUnavailable(RuntimeError):
    """The experiment was stored but could not be put on the queue (e.g. Redis down)."""


class Cancelled(Exception):
    """Raised inside a running experiment when its cancellation was requested."""


class BadCursor(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


# Pagination cursors: the (created_at, id) of the last item on a page, opaque to
# clients. Ordering by both makes pages stable even when rows share a timestamp,
# and new rows arriving between requests don't shift later pages (unlike offsets).

def encode_cursor(row) -> str:
    raw = json.dumps([row.created_at.isoformat(), row.id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        created, id_ = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(created), str(id_)
    except Exception:
        raise BadCursor("invalid cursor") from None


def _page(s, model, q, limit: int, cursor: str | None):
    """(rows, next_cursor), newest first."""
    if cursor:
        created, id_ = decode_cursor(cursor)
        q = q.where(or_(model.created_at < created, and_(model.created_at == created, model.id < id_)))
    rows = list(s.scalars(q.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
    return rows[:limit], (encode_cursor(rows[limit - 1]) if len(rows) > limit else None)


# ====================================================================== queues

class JobQueue(Protocol):
    def enqueue(self, experiment_id: str) -> None: ...
    def shutdown(self) -> None: ...


class ThreadQueue:
    """Runs experiments in a thread pool inside the API process."""

    def __init__(self, execute: Callable[[str], None], max_workers: int):
        self._execute = execute
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fruit-fly-exp")

    def enqueue(self, experiment_id: str) -> None:
        self._pool.submit(self._execute, experiment_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class RedisQueue:
    """Puts experiment IDs on a Redis queue (RQ); `python -m backend.app.worker` runs them."""

    NAME = "fruit_fly"

    def __init__(self, redis_url: str, job_timeout_s: int):
        from redis import Redis
        from rq import Queue

        self.connection = Redis.from_url(redis_url)
        self.queue = Queue(self.NAME, connection=self.connection)
        self.job_timeout_s = job_timeout_s

    def enqueue(self, experiment_id: str) -> None:
        self.queue.enqueue("backend.app.worker.run_job", experiment_id,
                           job_id=f"exp-{experiment_id}",
                           job_timeout=self.job_timeout_s,
                           result_ttl=0,               # results live in the database
                           failure_ttl=7 * 24 * 3600)

    def ping(self) -> bool:
        return bool(self.connection.ping())

    def shutdown(self) -> None:
        self.connection.close()


# ====================================================================== service

class JobService:
    def __init__(self, sessions: sessionmaker, spikes: LocalSpikeStore | S3SpikeStore, *,
                 max_pending: int, max_experiments: int, run: RunFn | None = None):
        self.sessions = sessions
        self.spikes = spikes
        self.max_pending = max_pending
        self.max_experiments = max_experiments
        self.run = run                      # None in an API process that doesn't execute jobs
        self.queue: JobQueue | None = None
        self.events: EventBus = NullBus()

    def _notify(self, experiment_id: str, sweep_id: str | None = None) -> None:
        self.events.publish(experiment_id, sweep_id)

    # ------------------------------------------------------------------ submission
    def _pending(self, s) -> int:
        return s.scalar(select(func.count()).select_from(ExperimentRow)
                        .where(ExperimentRow.status.in_(PENDING))) or 0

    def find_reusable(self, request_key: str) -> ExperimentRow | None:
        """A stand-alone experiment with this request key that has finished
        successfully or is still on its way (identical requests submitted close
        together share one run). Failed and cancelled ones are not reused."""
        with self.sessions() as s:
            return s.scalars(select(ExperimentRow)
                             .where(ExperimentRow.request_key == request_key,
                                    ExperimentRow.sweep_id.is_(None),
                                    ExperimentRow.status.in_(("queued", "running", "done")),
                                    ExperimentRow.cancel_requested.is_(False))
                             .order_by(ExperimentRow.created_at.desc()).limit(1)).first()

    def submit(self, request: ConditioningRequest, *, request_key: str | None = None,
               request_id: str | None = None, owner: str | None = None) -> ExperimentRow:
        with self.sessions() as s, s.begin():
            if self._pending(s) >= self.max_pending:
                raise CapacityError(f"{self.max_pending} experiments are already queued or running; "
                                    "try again later")
            row = ExperimentRow(id=new_id(), request=request.model_dump(mode="json"),
                                request_key=request_key, request_id=request_id, owner=owner)
            s.add(row)
        self._enqueue_all([row.id])
        return row

    def submit_sweep(self, sweep: SweepRow, members: list[tuple[float | str, ConditioningRequest]],
                     request_id: str | None = None) -> list[ExperimentRow]:
        """Create a sweep and all its experiments in one transaction, then enqueue them."""
        with self.sessions() as s, s.begin():
            if self._pending(s) + len(members) > self.max_pending:
                raise CapacityError(
                    f"this sweep needs {len(members)} slots but only "
                    f"{max(0, self.max_pending - self._pending(s))} of {self.max_pending} are free")
            s.add(sweep)
            # numeric values go in sweep_value, labels (lesion scans) in sweep_label
            rows = [ExperimentRow(id=new_id(), sweep_id=sweep.id,
                                  sweep_value=None if isinstance(value, str) else value,
                                  sweep_label=value if isinstance(value, str) else None,
                                  request=req.model_dump(mode="json"), store_spikes=False,
                                  request_id=request_id, owner=sweep.owner)
                    for value, req in members]
            s.add_all(rows)
        self._enqueue_all([r.id for r in rows])
        return rows

    def _enqueue_all(self, ids: list[str]) -> None:
        """Queue experiments whose rows are already committed. If the queue fails
        part-way, the rest are marked failed instead of staying "queued" forever
        (which would also block capacity), and QueueUnavailable is raised."""
        if self.queue is None:
            raise RuntimeError("no queue attached")
        for i, experiment_id in enumerate(ids):
            try:
                self.queue.enqueue(experiment_id)
            except Exception as e:
                log.exception("could not queue experiment %s", experiment_id)
                self._fail_where(ExperimentRow.id.in_(ids[i:]), ExperimentRow.status == "queued",
                                 error=f"could not be queued: {type(e).__name__}: {e}")
                raise QueueUnavailable("the experiment queue is unavailable; try again later") from e

    def _fail_where(self, *conditions, error: str) -> int:
        """Mark matching experiments failed in one statement; returns how many."""
        with self.sessions() as s, s.begin():
            return s.execute(update(ExperimentRow).where(*conditions)
                             .values(status="failed", error=error, finished_at=utcnow())
                             .execution_options(synchronize_session=False)).rowcount

    # ------------------------------------------------------------------ queries
    def get(self, experiment_id: str) -> ExperimentRow | None:
        with self.sessions() as s:
            return s.get(ExperimentRow, experiment_id)

    def list(self, include_sweeps: bool = False, limit: int = 50,
             cursor: str | None = None) -> tuple[list[ExperimentRow], str | None]:
        """One page, newest first, and the cursor of the next page (None at the end)."""
        q = select(ExperimentRow)
        if not include_sweeps:
            q = q.where(ExperimentRow.sweep_id.is_(None))
        with self.sessions() as s:
            return _page(s, ExperimentRow, q, limit, cursor)

    def get_sweep(self, sweep_id: str) -> SweepRow | None:
        with self.sessions() as s:
            return s.get(SweepRow, sweep_id)

    def list_sweeps(self, limit: int = 50, cursor: str | None = None) -> tuple[list[SweepRow], str | None]:
        with self.sessions() as s:
            return _page(s, SweepRow, select(SweepRow), limit, cursor)

    def sweep_counts(self, sweep_ids: list[str]) -> dict[str, dict[str, int]]:
        """Experiments per status for each sweep, in one grouped query (listing
        sweeps must not load every member's result document)."""
        counts: dict[str, dict[str, int]] = {
            i: {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0} for i in sweep_ids}
        if not sweep_ids:
            return counts
        q = (select(ExperimentRow.sweep_id, ExperimentRow.status, func.count())
             .where(ExperimentRow.sweep_id.in_(sweep_ids))
             .group_by(ExperimentRow.sweep_id, ExperimentRow.status))
        with self.sessions() as s:
            for sweep_id, status, n in s.execute(q):
                counts[sweep_id][status] = n
        return counts

    def sweep_members(self, sweep_id: str) -> list[ExperimentRow]:
        with self.sessions() as s:
            return list(s.scalars(select(ExperimentRow).where(ExperimentRow.sweep_id == sweep_id)
                                  .order_by(ExperimentRow.created_at, ExperimentRow.id)))

    # ------------------------------------------------------------------ cancellation
    def cancel(self, experiment_id: str) -> str | None:
        """Stop an experiment. Returns its status afterwards: "cancelled" (it was
        queued: no worker will start it, because claiming requires "queued"),
        "running" (the worker will stop at the next presentation), or a finished
        status if it was already done. None if unknown."""
        with self.sessions() as s, s.begin():
            dequeued = s.execute(
                update(ExperimentRow)
                .where(ExperimentRow.id == experiment_id, ExperimentRow.status == "queued")
                .values(status="cancelled", error="cancelled before it started", finished_at=utcnow())
                .execution_options(synchronize_session=False)).rowcount
            if not dequeued:
                s.execute(update(ExperimentRow)
                          .where(ExperimentRow.id == experiment_id, ExperimentRow.status == "running")
                          .values(cancel_requested=True)
                          .execution_options(synchronize_session=False))
            row = s.get(ExperimentRow, experiment_id)
            if row is None:
                return None
            status, sweep_id = row.status, row.sweep_id
        self._notify(experiment_id, sweep_id)
        return status

    def cancel_sweep(self, sweep_id: str) -> dict[str, int] | None:
        """Cancel every queued member at once and flag the running ones.
        Returns how many of each, or None if the sweep is unknown."""
        with self.sessions() as s, s.begin():
            if s.get(SweepRow, sweep_id) is None:
                return None
            dequeued = s.execute(
                update(ExperimentRow)
                .where(ExperimentRow.sweep_id == sweep_id, ExperimentRow.status == "queued")
                .values(status="cancelled", error="cancelled before it started", finished_at=utcnow())
                .execution_options(synchronize_session=False)).rowcount
            stopping = s.execute(
                update(ExperimentRow)
                .where(ExperimentRow.sweep_id == sweep_id, ExperimentRow.status == "running")
                .values(cancel_requested=True)
                .execution_options(synchronize_session=False)).rowcount
        self.events.publish(sweep_id)
        return {"cancelled": dequeued, "stopping": stopping}

    # ------------------------------------------------------------------ deletion
    def delete(self, experiment_id: str) -> bool:
        """Remove a finished experiment. False if unknown; RuntimeError if still pending."""
        with self.sessions() as s, s.begin():
            row = s.get(ExperimentRow, experiment_id)
            if row is None:
                return False
            if not row.finished:
                raise RuntimeError("experiment is still queued or running")
            s.delete(row)
        self.spikes.delete(experiment_id)
        return True

    def delete_sweep(self, sweep_id: str) -> bool:
        with self.sessions() as s, s.begin():
            sweep = s.get(SweepRow, sweep_id)
            if sweep is None:
                return False
            members = list(s.scalars(select(ExperimentRow).where(ExperimentRow.sweep_id == sweep_id)))
            if any(not m.finished for m in members):
                raise RuntimeError("sweep still has queued or running experiments")
            for m in members:
                s.delete(m)
            s.delete(sweep)
        for m in members:
            self.spikes.delete(m.id)
        return True

    # ------------------------------------------------------------------ execution
    def execute(self, experiment_id: str) -> None:
        """Run one experiment. Safe to call twice: finished experiments are skipped."""
        if self.run is None:
            raise RuntimeError("this JobService cannot execute experiments")
        # Claim atomically: a conditional UPDATE succeeds for exactly one caller,
        # even if two workers receive the same experiment at the same moment.
        # (Reading "queued" and then writing "running" would let both through.)
        with self.sessions() as s, s.begin():
            claimed = s.execute(
                update(ExperimentRow)
                .where(ExperimentRow.id == experiment_id, ExperimentRow.status == "queued")
                .values(status="running", started_at=utcnow())
                .execution_options(synchronize_session=False)).rowcount
            if claimed != 1:
                row = s.get(ExperimentRow, experiment_id)
                log.info("skipping experiment %s (%s)", experiment_id, row.status if row else "deleted")
                return
            row = s.get(ExperimentRow, experiment_id)
            request = ConditioningRequest.model_validate(row.request)
            store_spikes, sweep_id, request_id = row.store_spikes, row.sweep_id, row.request_id

        with experiment_context(experiment_id, request_id):
            self._notify(experiment_id, sweep_id)
            log.info("experiment started")

            def report(done: int, total: int) -> None:
                """Called by the simulator after each odour presentation: store
                progress, and stop if cancellation was requested."""
                with self.sessions() as s, s.begin():
                    r = s.get(ExperimentRow, experiment_id)
                    if r is None:
                        raise Cancelled("deleted")
                    r.progress_done, r.progress_total = done, total
                    stop = r.cancel_requested
                self._notify(experiment_id)
                if stop:
                    raise Cancelled("cancelled")

            try:
                output = self.run(request, report)
                if store_spikes:
                    self.spikes.save(experiment_id, output.spike_neurons, output.spike_times)
            except Cancelled:
                log.info("experiment cancelled while running")
                self._finish(experiment_id, sweep_id, status="cancelled", error="cancelled while running")
                return
            except Exception as e:                   # report it; never crash the worker
                log.exception("experiment failed")
                self._finish(experiment_id, sweep_id, status="failed", error=f"{type(e).__name__}: {e}")
                return
            self._finish(experiment_id, sweep_id, status="done", result=output.result)
            log.info("experiment finished")
        self._prune()

    def _finish(self, experiment_id: str, sweep_id: str | None, *, status: str,
                result: dict | None = None, error: str | None = None) -> None:
        with self.sessions() as s, s.begin():
            row = s.get(ExperimentRow, experiment_id)
            if row is None:                       # deleted while running
                self.spikes.delete(experiment_id)
                return
            row.status, row.result, row.error = status, result, error
            row.finished_at = utcnow()
        self._notify(experiment_id, sweep_id)

    def _prune(self) -> None:
        """Keep at most max_experiments finished single experiments (sweeps are kept whole)."""
        with self.sessions() as s, s.begin():
            old = list(s.scalars(
                select(ExperimentRow)
                .where(ExperimentRow.sweep_id.is_(None), ExperimentRow.status.in_(FINISHED))
                .order_by(ExperimentRow.created_at.desc())
                .offset(self.max_experiments)))
            for row in old:
                s.delete(row)
        for row in old:
            self.spikes.delete(row.id)

    # ------------------------------------------------------------------ recovery
    def recover_after_restart(self) -> tuple[int, int]:
        """For the in-process queue: jobs lived in memory and are gone after a
        restart. Re-enqueue experiments that never started; fail the ones that
        were interrupted. Returns (requeued, failed)."""
        with self.sessions() as s, s.begin():
            interrupted = list(s.scalars(select(ExperimentRow).where(ExperimentRow.status == "running")))
            for row in interrupted:
                row.status = "failed"
                row.error = "interrupted by a server restart"
                row.finished_at = utcnow()
            queued = [r.id for r in s.scalars(select(ExperimentRow)
                                              .where(ExperimentRow.status == "queued")
                                              .order_by(ExperimentRow.created_at))]
        if queued:
            self._enqueue_all(queued)
        return len(queued), len(interrupted)

    def fail_stale(self, older_than_s: float) -> int:
        """For worker processes: an experiment still "running" after the job
        timeout belongs to a worker that died (crash, OOM kill, lost machine).
        Mark it failed so it doesn't hang forever. Returns how many."""
        cutoff = utcnow() - timedelta(seconds=older_than_s)
        return self._fail_where(
            ExperimentRow.status == "running", ExperimentRow.started_at < cutoff,
            error=f"no result after {int(older_than_s)} s; the worker running it probably stopped")