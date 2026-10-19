"""Live progress (server-sent events), cancellation, result reuse, exports and
request ids, through the HTTP API."""

import csv
import io
import json
import logging

from fastapi.testclient import TestClient

from backend.app import logs
from backend.app.main import create_app

from .conftest import FAST, make_settings, require_data, wait_for

URL = "/api/experiments/conditioning"
BODY = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST}
SLOW = {**BODY, "trials": 6, "protocol": {"stim_ms": 500, "gap_ms": 500, "settle_ms": 100}}


def events(client, path: str) -> list[tuple[str, dict]]:
    """All events of a server-sent event stream, until the server closes it.
    (TestClient hands over a streamed body only when it ends; real clients get
    each event as it is sent.)"""
    out, event = [], None
    with client.stream("GET", path) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                out.append((event, json.loads(line[6:])))
    return out


def test_experiment_events_stream_progress_then_end(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path))) as client:
        job = client.post(URL, json={**BODY, "trials": 2}).json()
        got = events(client, f"/api/experiments/{job['id']}/events")
        kinds = [k for k, _ in got]
        assert kinds[-1] == "end" and set(kinds[:-1]) == {"update"}
        updates = [d for k, d in got if k == "update"]
        assert updates[-1]["status"] == "done"
        progress = [u["progress"]["done"] for u in updates if u["progress"]]
        assert progress == sorted(progress) and len(progress) >= 2     # more than just the final state
        # a finished experiment: one update, then end
        assert [k for k, _ in events(client, f"/api/experiments/{job['id']}/events")] == ["update", "end"]
        assert client.get("/api/experiments/0123456789abcdef0123456789abcdef/events").status_code == 404


def test_cancel_through_the_api(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path, max_workers=1))) as client:
        running = client.post(URL, json={**SLOW, "seed": 1}).json()["id"]
        queued = client.post(URL, json={**SLOW, "seed": 2}).json()["id"]    # waits: one worker
        assert client.post(f"/api/experiments/{queued}/cancel").json() == {"status": "cancelled"}
        r = client.post(f"/api/experiments/{running}/cancel")
        assert r.status_code == 200 and r.json()["status"] in ("running", "cancelled")
        final = events(client, f"/api/experiments/{running}/events")
        assert final[-2][1]["status"] == "cancelled" and final[-1][0] == "end"
        assert wait_for(client, queued)["started_at"] is None
        done = client.post(URL, json=BODY).json()["id"]
        wait_for(client, done)
        assert client.post(f"/api/experiments/{done}/cancel").status_code == 409
        # cancelled experiments are never reused: the same request runs again
        again = client.post(URL, json={**SLOW, "seed": 2})
        assert again.status_code == 202 and again.json()["id"] != queued
        client.post(f"/api/experiments/{again.json()['id']}/cancel")


def test_identical_requests_share_one_experiment(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path, rate_limit=2))) as client:
        first = client.post(URL, json=BODY)
        assert first.status_code == 202
        same = client.post(URL, json=BODY)                  # while it is still running
        assert same.status_code == 200 and same.json()["id"] == first.json()["id"]
        wait_for(client, first.json()["id"])
        # reused after it finished too, and reuse is free: these don't hit the rate limit
        for _ in range(3):
            assert client.post(URL, json=BODY).json()["id"] == first.json()["id"]
        # odour names are canonicalised before the key is computed, so spelling doesn't matter
        fresh = client.post(URL, params={"reuse": "false"}, json=BODY)
        assert fresh.status_code == 202 and fresh.json()["id"] != first.json()["id"]
        assert client.post(URL, json={**BODY, "seed": 2}).status_code == 429   # 2 real runs used the limit
        metrics = client.get("/metrics").text
        assert 'fruit_fly_experiments_submitted_total{kind="reused"} 4.0' in metrics
        wait_for(client, fresh.json()["id"])


def test_exports(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path))) as client:
        job_id = client.post(URL, json=BODY).json()["id"]
        detail = wait_for(client, job_id)

        r = client.get(f"/api/experiments/{job_id}/export.json")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        body = r.json()
        assert body["result"] == detail["result"] and len(body["model_fingerprint"]) == 64

        r = client.get(f"/api/experiments/{job_id}/mbons.csv")
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert r.headers["content-type"].startswith("text/csv")
        assert [row["cell_type"] for row in rows] == [m["cell_type"] for m in detail["result"]["mbons"]]
        assert all(row["weight_ratio"] for row in rows)

        r = client.get(f"/api/experiments/{job_id}/spikes.csv")
        lines = r.text.splitlines()
        assert lines[0] == "time_ms,neuron,root_id,group,cell_type"
        assert len(lines) - 1 == detail["result"]["n_spikes"]          # every spike, once
        times = [float(line.split(",")[0]) for line in lines[1:]]
        assert times == sorted(times)
        kc_only = client.get(f"/api/experiments/{job_id}/spikes.csv", params={"group": "KC"}).text
        assert all(line.split(",")[3] == "KC" for line in kc_only.splitlines()[1:])
        assert client.get(f"/api/experiments/{job_id}/spikes.csv", params={"group": "X"}).status_code == 422


def test_sweep_events_and_cancel(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path, max_workers=1))) as client:
        sweep = client.post("/api/sweeps", json={"base": SLOW, "parameter": "trials",
                                                 "values": [5, 6], "repeats": 2}).json()
        out = client.post(f"/api/sweeps/{sweep['id']}/cancel").json()
        assert out["cancelled"] + out["stopping"] == 4
        got = events(client, f"/api/sweeps/{sweep['id']}/events")
        assert got[-1][0] == "end"
        last = got[-2][1]
        assert last["status"] == "cancelled" and last["counts"]["cancelled"] == 4
        page = client.get("/api/sweeps", params={"limit": 1}).json()
        assert [s["id"] for s in page["items"]] == [sweep["id"]] and page["next_cursor"] is None


def test_list_pages_through_the_api(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path))) as client:
        ids = [client.post(URL, json={**BODY, "seed": k}).json()["id"] for k in range(5)]
        seen, cursor = [], None
        while True:
            page = client.get("/api/experiments", params={"limit": 2, **({"cursor": cursor} if cursor else {})})
            body = page.json()
            seen += [e["id"] for e in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == ids[::-1]
        assert client.get("/api/experiments", params={"cursor": "bad"}).status_code == 422
        for i in ids:
            wait_for(client, i)


def test_request_ids_follow_a_job_into_the_worker(tmp_path, capsys):
    require_data()
    with TestClient(create_app(make_settings(tmp_path, log_format="json"))) as client:
        r = client.get("/api/health", headers={"X-Request-ID": "trace-123", "X-Forwarded-For": "203.0.113.7"})
        assert r.headers["x-request-id"] == "trace-123"
        generated = client.get("/api/health", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"]
        assert generated != "bad id\n" and len(generated) == 32           # replaced, not echoed
        job = client.post(URL, json=BODY, headers={"X-Request-ID": "submit-1"}).json()
        wait_for(client, job["id"])
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    access = [l for l in lines if l["logger"] == "fruit_fly.access" and l.get("request_id") == "trace-123"]
    assert access and access[0]["route"] == "/api/health" and access[0]["status"] == 200
    assert access[0]["forwarded_for"] == "203.0.113.7"                   # for checking FRUIT_FLY_PROXY_HOPS
    worker = [l for l in lines if l["logger"] == "fruit_fly.jobs" and l.get("experiment_id") == job["id"]]
    assert {l["message"] for l in worker} >= {"experiment started", "experiment finished"}
    assert all(l["request_id"] == "submit-1" for l in worker)           # the id that queued it
    logs.configure("text")                                               # leave text logs for later tests
    logging.getLogger("fruit_fly").setLevel(logging.INFO)
