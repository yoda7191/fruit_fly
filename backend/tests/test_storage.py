"""Persistence, restart recovery and retention (in-process queue, SQLite)."""

import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db import ExperimentRow, init_db, make_engine, make_sessionmaker
from backend.app.main import create_app

from .conftest import FAST, make_settings, require_data, wait_for

RANDOM = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST}


def test_experiments_survive_a_restart(tmp_path):
    require_data()
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        job_id = c.post("/api/experiments/conditioning", json=RANDOM).json()["id"]
        first = wait_for(c, job_id)
        assert first["status"] == "done"
    with TestClient(create_app(settings)) as c:                  # a new server process
        again = c.get(f"/api/experiments/{job_id}").json()
        assert again["status"] == "done"
        assert again["result"] == first["result"]
        spikes = c.get(f"/api/experiments/{job_id}/spikes", params={"t0_ms": 0, "t1_ms": 1000}).json()
        assert spikes["count"] > 0
        assert [e["id"] for e in c.get("/api/experiments").json()["items"]] == [job_id]


def test_restart_requeues_queued_and_fails_interrupted(tmp_path):
    require_data()
    settings = make_settings(tmp_path)
    engine = make_engine(settings.db_url)
    init_db(engine)
    sessions = make_sessionmaker(engine)
    request = {"cs_plus": "A", "cs_minus": "B", "odour_source": "random", "trials": 1,
               "us": "shock", "seed": 1, "params": {}, "behavior": {"sharpness": 6.0, "flies": 100},
               "protocol": {"stim_ms": 400, "gap_ms": 600, "settle_ms": 100, "us_hz": 40.0}}
    with sessions() as s, s.begin():                              # as left by a crashed server
        s.add(ExperimentRow(id="a" * 32, status="queued", request=request))
        s.add(ExperimentRow(id="b" * 32, status="running", request=request))
    engine.dispose()

    with TestClient(create_app(settings)) as c:
        interrupted = c.get(f"/api/experiments/{'b' * 32}").json()
        assert interrupted["status"] == "failed"
        assert "restart" in interrupted["error"]
        assert wait_for(c, "a" * 32)["status"] == "done"          # picked up again


def test_old_experiments_are_pruned(tmp_path):
    require_data()
    settings = make_settings(tmp_path, max_experiments=2)
    with TestClient(create_app(settings)) as c:
        ids = []
        for k in range(3):
            ids.append(c.post("/api/experiments/conditioning", json={**RANDOM, "seed": k + 1}).json()["id"])
            wait_for(c, ids[-1])
            time.sleep(0.01)                                      # distinct creation times
        listed = [e["id"] for e in c.get("/api/experiments").json()["items"]]
        assert listed == [ids[2], ids[1]]
        assert c.get(f"/api/experiments/{ids[0]}").status_code == 404
        assert not (settings.runs_dir / ids[0]).exists()          # spike files removed too


def test_database_rows_match_the_api(tmp_path):
    require_data()
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        job_id = c.post("/api/experiments/conditioning", json=RANDOM).json()["id"]
        wait_for(c, job_id)
    engine = make_engine(settings.db_url)
    with make_sessionmaker(engine)() as s:
        row = s.scalars(select(ExperimentRow)).one()
        assert row.id == job_id and row.status == "done"
        assert row.progress_done == row.progress_total == 6
        assert "behavior" in row.result
    engine.dispose()