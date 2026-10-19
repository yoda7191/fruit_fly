"""The production setup: PostgreSQL + Redis + a separate worker process.

Skipped unless both services are configured:
    FRUIT_FLY_TEST_DATABASE_URL=postgresql+psycopg://fruit_fly:fruit_fly@localhost:5432/fruit_fly_test
    FRUIT_FLY_TEST_REDIS_URL=redis://localhost:6379/15
The test database is wiped at the start.
"""

import multiprocessing as mp
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.config import REPO_ROOT
from backend.app.db import drop_db, make_engine
from backend.app.main import create_app

from .conftest import FAST, make_settings, require_data, wait_for, wait_for_sweep

DB_URL = os.environ.get("FRUIT_FLY_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("FRUIT_FLY_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not (DB_URL and REDIS_URL),
                                reason="set FRUIT_FLY_TEST_DATABASE_URL and FRUIT_FLY_TEST_REDIS_URL")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    require_data()
    from redis import Redis
    Redis.from_url(REDIS_URL).flushdb()
    engine = make_engine(DB_URL)
    drop_db(engine)
    engine.dispose()

    folder = tmp_path_factory.mktemp("redis-stack")
    settings = make_settings(folder, database_url=DB_URL, queue="redis", redis_url=REDIS_URL)
    env = {**os.environ, "FRUIT_FLY_DATABASE_URL": DB_URL, "FRUIT_FLY_QUEUE": "redis",
           "FRUIT_FLY_REDIS_URL": REDIS_URL, "FRUIT_FLY_STORAGE_DIR": str(settings.runs_dir),
           "FRUIT_FLY_CIRCUIT_DIR": str(settings.circuit_dir), "FRUIT_FLY_DOOR_DIR": str(settings.door_dir)}
    with TestClient(create_app(settings)) as client:    # creates the tables first
        workers = [subprocess.Popen([sys.executable, "-m", "backend.app.worker"], cwd=REPO_ROOT,
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
                   for _ in range(2)]
        try:
            yield client, settings
        finally:
            for w in workers:
                w.terminate()
            for w in workers:
                w.wait(timeout=20)


def _create_tables(url, barrier, results):
    from backend.app.db import init_db, make_engine
    engine = make_engine(url)
    barrier.wait()                                     # everyone starts at the same moment
    try:
        init_db(engine)
        results.put("ok")
    except Exception as e:                            # report instead of crashing the child
        results.put(type(e).__name__)
    finally:
        engine.dispose()


def test_concurrent_startup_creates_tables_safely():
    """API and workers start together on a fresh database. Without the advisory
    lock in init_db, 3 of 4 concurrent create_all calls failed every time."""
    engine = make_engine(DB_URL)
    drop_db(engine)
    engine.dispose()
    ctx = mp.get_context("spawn")
    barrier, results = ctx.Barrier(4), ctx.Queue()
    procs = [ctx.Process(target=_create_tables, args=(DB_URL, barrier, results)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    assert sorted(results.get(timeout=5) for _ in procs) == ["ok"] * 4


def test_health_reports_redis_and_postgres(stack):
    client, _ = stack
    body = client.get("/api/health").json()
    assert body == {**body, "status": "ok", "queue": "redis", "queue_ok": True,
                    "database": "postgresql"}


def test_worker_runs_experiments(stack):
    client, settings = stack
    job_id = client.post("/api/experiments/conditioning",
                         json={"cs_plus": "ethyl acetate", "cs_minus": "benzaldehyde", **FAST}).json()["id"]
    body = wait_for(client, job_id)
    assert body["status"] == "done", body["error"]
    assert body["progress"] == {"done": 6, "total": 6}
    assert "behavior" in body["result"]
    spikes = client.get(f"/api/experiments/{job_id}/spikes", params={"t0_ms": 0, "t1_ms": 1000}).json()
    assert spikes["count"] > 0                           # written by the worker, read by the API


def test_live_events_and_cancel_across_processes(stack):
    """Progress reaches the API's event stream from a worker process through
    Redis pub/sub, and a cancel written by the API stops a job in a worker."""
    from .test_live import SLOW, events
    client, _ = stack
    job = client.post("/api/experiments/conditioning", json={**SLOW, "seed": 77}).json()
    # (TestClient delivers a stream only once it ends, so poll to catch it mid-run)
    deadline = time.monotonic() + 60
    while not client.get(f"/api/experiments/{job['id']}").json()["progress"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    r = client.post(f"/api/experiments/{job['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "running", r.text
    got = events(client, f"/api/experiments/{job['id']}/events")
    assert got[-1][0] == "end" and got[-2][1]["status"] == "cancelled"
    progress = got[-2][1]["progress"]
    assert progress["done"] < progress["total"]               # stopped part-way


def test_sweep_through_workers_and_persistence(stack):
    client, settings = stack
    sweep_id = client.post("/api/sweeps", json={
        "base": {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST},
        "parameter": "trials", "values": [0, 1], "repeats": 2}).json()["id"]
    body = wait_for_sweep(client, sweep_id)
    assert body["counts"]["done"] == 4
    # a fresh API process sees everything (state lives in PostgreSQL)
    with TestClient(create_app(settings)) as other:
        assert other.get(f"/api/sweeps/{sweep_id}").json()["counts"]["done"] == 4

def test_redis_rate_limiter_is_shared_and_atomic():
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.ratelimit import RateLimited, RedisRateLimiter

    clock = lambda: 1_000_020.0                                  # one fixed window
    prefix = f"fruit_fly:test-rate:{time.time_ns()}"
    a = RedisRateLimiter(REDIS_URL, limit=5, clock=clock, prefix=prefix)
    b = RedisRateLimiter(REDIS_URL, limit=5, clock=clock, prefix=prefix)   # "another process"

    def try_charge(rl):
        try:
            rl.charge("client", 1)
            return True
        except RateLimited:
            return False

    with ThreadPoolExecutor(8) as pool:                          # 20 racing requests, 5 allowed
        accepted = sum(pool.map(try_charge, [a, b] * 10))
    assert accepted == 5
    with pytest.raises(RateLimited):
        a.charge("client", 1)
    b.charge("other", 5)                                         # per client
