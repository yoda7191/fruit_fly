"""JobService behaviour that matters under concurrency and failure.

Runs against SQLite, and also against PostgreSQL when FRUIT_FLY_TEST_DATABASE_URL
is set (the two databases handle concurrent writes differently).
"""

import os
import threading
import time
from datetime import timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import update

from backend.app import sweeps as sweep_logic
from backend.app.db import ExperimentRow, SweepRow, drop_db, init_db, make_engine, make_sessionmaker, utcnow
from backend.app.jobs import CapacityError, JobService, QueueUnavailable, new_id
from backend.app.runner import RunOutput
from backend.app.schemas import ConditioningRequest
from backend.app.spikes import SpikeStore

DATABASES = ["sqlite"] + (["postgresql"] if os.environ.get("FRUIT_FLY_TEST_DATABASE_URL") else [])


class ListQueue:
    """Records enqueued IDs; optionally fails from the n-th call on."""

    def __init__(self, fail_from: int | None = None):
        self.ids: list[str] = []
        self.fail_from = fail_from

    def enqueue(self, experiment_id: str) -> None:
        if self.fail_from is not None and len(self.ids) >= self.fail_from:
            raise ConnectionError("redis is down")
        self.ids.append(experiment_id)

    def shutdown(self) -> None:
        pass


def fake_run(calls: list, delay: float = 0.0):
    def run(request, progress):
        calls.append(request)
        time.sleep(delay)
        progress(1, 1)
        return RunOutput(result={"ok": True}, spike_neurons=np.array([1, 2], np.int32),
                         spike_times=np.array([0.5, 1.5], np.float32))
    return run


@pytest.fixture(params=DATABASES)
def make_service(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path}/jobs.db"
    else:
        url = os.environ["FRUIT_FLY_TEST_DATABASE_URL"]
    engine = make_engine(url)
    drop_db(engine)
    init_db(engine)

    def factory(run=None, queue=None, max_pending=50):
        service = JobService(make_sessionmaker(engine), SpikeStore(tmp_path / "runs"),
                             max_pending=max_pending, max_experiments=100, run=run)
        service.queue = queue or ListQueue()
        return service

    yield factory
    engine.dispose()


REQ = ConditioningRequest(odour_source="random", cs_plus="A", cs_minus="B")


def test_experiment_runs_once_even_if_two_workers_race(make_service):
    calls: list = []
    service = make_service(run=fake_run(calls, delay=0.2))
    row = service.submit(REQ)
    start = threading.Barrier(4)

    def worker():
        start.wait()                        # all four try to claim at the same moment
        service.execute(row.id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert service.get(row.id).status == "done"


def test_queue_failure_marks_experiments_failed_and_frees_capacity(make_service):
    service = make_service(queue=ListQueue(fail_from=0), max_pending=2)
    with pytest.raises(QueueUnavailable):
        service.submit(REQ)
    rows, _ = service.list()
    assert len(rows) == 1 and rows[0].status == "failed"
    assert "could not be queued" in rows[0].error
    service.queue = ListQueue()             # queue back: capacity is not used up by the failure
    service.submit(REQ)
    service.submit(REQ)
    with pytest.raises(CapacityError):
        service.submit(REQ)


def test_partially_queued_sweep_fails_only_the_rest(make_service):
    service = make_service(queue=ListQueue(fail_from=2))
    sweep = SweepRow(id=new_id(), parameter="trials", values=[1, 2, 3], repeats=1,
                     base_request=REQ.model_dump(mode="json"))
    with pytest.raises(QueueUnavailable):
        service.submit_sweep(sweep, [(v, REQ) for v in (1, 2, 3)])
    counts = service.sweep_counts([sweep.id])[sweep.id]
    assert counts == {"queued": 2, "running": 0, "done": 0, "failed": 1, "cancelled": 0}


def test_stale_running_experiments_are_failed(make_service):
    service = make_service()
    old, recent = service.submit(REQ), service.submit(REQ)
    with service.sessions() as s, s.begin():
        s.execute(update(ExperimentRow).where(ExperimentRow.id == old.id)
                  .values(status="running", started_at=utcnow() - timedelta(hours=2)))
        s.execute(update(ExperimentRow).where(ExperimentRow.id == recent.id)
                  .values(status="running", started_at=utcnow()))
    assert service.fail_stale(3600) == 1
    assert service.get(old.id).status == "failed"
    assert "worker" in service.get(old.id).error
    assert service.get(recent.id).status == "running"


def test_timestamps_are_utc_aware(make_service):
    calls: list = []
    service = make_service(run=fake_run(calls))
    row = service.submit(REQ)
    service.execute(row.id)
    stored = service.get(row.id)
    for ts in (stored.created_at, stored.started_at, stored.finished_at):
        assert ts.tzinfo is not None and ts.utcoffset() == timedelta(0)
    assert abs(stored.created_at - utcnow()) < timedelta(minutes=1)
    with pytest.raises(Exception):          # naive datetimes are refused, not silently stored
        with service.sessions() as s, s.begin():
            s.execute(update(ExperimentRow).values(started_at=utcnow().replace(tzinfo=None)))


def test_sweep_counts_in_one_query_and_status_rules(make_service):
    service = make_service()
    sweep = SweepRow(id=new_id(), parameter="trials", values=[1, 2], repeats=2,
                     base_request=REQ.model_dump(mode="json"))
    rows = service.submit_sweep(sweep, [(v, REQ) for v in (1, 1, 2, 2)])
    statuses = ["done", "done", "done", "failed"]
    with service.sessions() as s, s.begin():
        for r, st in zip(rows, statuses):
            s.execute(update(ExperimentRow).where(ExperimentRow.id == r.id).values(status=st))
    counts = service.sweep_counts([sweep.id, "missing"])
    assert counts[sweep.id] == {"queued": 0, "running": 0, "done": 3, "failed": 1, "cancelled": 0}
    assert counts["missing"]["done"] == 0
    assert sweep_logic.summarize(sweep, counts[sweep.id])["status"] == "done"   # partial failure
    assert sweep_logic.summarize(sweep, {"failed": 4})["status"] == "failed"
    assert sweep_logic.summarize(sweep, {"done": 3, "queued": 1})["status"] == "running"

# ---------------------------------------------------------------- cancellation

def test_cancel_queued_experiment_never_runs(make_service):
    calls = []
    service = make_service(run=fake_run(calls))
    row = service.submit(REQ)
    assert service.cancel(row.id) == "cancelled"
    service.execute(row.id)                      # the queue still delivers it: the claim must fail
    assert calls == []
    got = service.get(row.id)
    assert got.status == "cancelled" and got.started_at is None and got.finished
    assert service.cancel(row.id) == "cancelled"                  # idempotent
    assert service.cancel(new_id()) is None


def test_cancel_running_experiment_stops_at_next_presentation(make_service):
    started = threading.Event()
    presentations = []

    def run(request, progress):
        for i in range(1, 200):
            presentations.append(i)
            progress(i, 200)                     # raises once cancellation was requested
            started.set()
            time.sleep(0.01)
        raise AssertionError("never cancelled")

    service = make_service(run=run)
    row = service.submit(REQ)
    t = threading.Thread(target=service.execute, args=(row.id,))
    t.start()
    assert started.wait(5)
    assert service.cancel(row.id) == "running"   # flagged; the worker stops on its own
    t.join(5)
    got = service.get(row.id)
    assert got.status == "cancelled" and "while running" in got.error
    assert len(presentations) < 200
    assert not service.spikes.exists(row.id)
    # a cancelled experiment frees its slot and can be deleted
    assert service.delete(row.id)


def test_cancel_finished_experiment_changes_nothing(make_service):
    service = make_service(run=fake_run([]))
    row = service.submit(REQ)
    service.execute(row.id)
    assert service.cancel(row.id) == "done"
    assert service.get(row.id).status == "done"


def test_cancel_sweep(make_service):
    service = make_service(run=fake_run([]))
    sweep = SweepRow(id=new_id(), parameter="trials", values=[1, 2], repeats=2, base_request={})
    rows = service.submit_sweep(sweep, [(v, REQ) for v in (1, 1, 2, 2)])
    service.execute(rows[0].id)
    with service.sessions() as s, s.begin():                    # one member mid-run
        s.execute(update(ExperimentRow).where(ExperimentRow.id == rows[1].id).values(status="running"))
    assert service.cancel_sweep(sweep.id) == {"cancelled": 2, "stopping": 1}
    counts = service.sweep_counts([sweep.id])[sweep.id]
    assert counts == {"queued": 0, "running": 1, "done": 1, "failed": 0, "cancelled": 2}
    assert sweep_logic.summarize(sweep, {**counts, "running": 0})["status"] == "done"
    assert sweep_logic.summarize(sweep, {"cancelled": 4})["status"] == "cancelled"
    assert service.cancel_sweep(new_id()) is None


# ---------------------------------------------------------------- reuse and paging

def test_find_reusable_skips_failed_cancelled_and_sweep_members(make_service):
    service = make_service(run=fake_run([]))
    a = service.submit(REQ, request_key="k")
    assert service.find_reusable("k").id == a.id             # queued: shared
    service.cancel(a.id)
    assert service.find_reusable("k") is None                # cancelled: not reused
    b = service.submit(REQ, request_key="k")
    service.execute(b.id)
    assert service.find_reusable("k").id == b.id             # done
    assert service.find_reusable("other") is None


def test_pages_are_stable_when_rows_share_a_timestamp(make_service):
    service = make_service()
    same = utcnow()
    with service.sessions() as s, s.begin():
        ids = sorted(new_id() for _ in range(7))
        s.add_all(ExperimentRow(id=i, request={}, created_at=same) for i in ids)
    seen, cursor = [], None
    while True:
        rows, cursor = service.list(limit=3, cursor=cursor)
        seen += [r.id for r in rows]
        if cursor is None:
            break
    assert seen == sorted(ids, reverse=True)                 # each once, in a fixed order
    # a row added after the first page doesn't shift the later pages
    first, cursor = service.list(limit=3)
    service.submit(REQ)
    rest, _ = service.list(limit=10, cursor=cursor)
    assert [r.id for r in first + rest] == sorted(ids, reverse=True)


def test_bad_cursor(make_service):
    from backend.app.jobs import BadCursor
    with pytest.raises(BadCursor):
        make_service().list(cursor="not-a-cursor")
