"""Prometheus metrics at /metrics."""

import re

from fastapi.testclient import TestClient

from backend.app.main import create_app

from .conftest import FAST, make_settings, require_data, wait_for

BODY = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST}


def value(text: str, name: str, **labels) -> float:
    """The value of one sample in Prometheus text format (0 if absent)."""
    want = ",".join(f'{k}="{v}"' for k, v in labels.items())
    pattern = rf"^{re.escape(name)}{re.escape('{' + want + '}') if want else ''} (\S+)$"
    m = re.search(pattern, text, re.M)
    return float(m.group(1)) if m else 0.0


def test_metrics_cover_requests_events_and_queue(tmp_path):
    require_data()
    with TestClient(create_app(make_settings(tmp_path, require_api_key=True, rate_limit=2))) as client:
        from backend.app import apikeys
        _, key = apikeys.create(client.app.state.sessions, "metrics")
        auth = {"X-API-Key": key}
        client.get("/api/health")
        assert client.post("/api/experiments/conditioning", json=BODY).status_code == 401
        ids = [client.post("/api/experiments/conditioning", json={**BODY, "seed": k}, headers=auth).json()["id"]
               for k in range(2)]
        assert client.post("/api/experiments/conditioning", json={**BODY, "seed": 2},
                           headers=auth).status_code == 429
        client.get(f"/api/experiments/{ids[0]}")
        client.get("/api/does-not-exist")

        r = client.get("/metrics")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
        text = r.text
        assert value(text, "fruit_fly_http_requests_total", method="GET", route="/api/health", status="200") == 1
        # route templates, not ids: bounded label sets
        assert value(text, "fruit_fly_http_requests_total", method="GET",
                     route="/api/experiments/{experiment_id}", status="200") == 1
        assert ids[0] not in text and "does-not-exist" not in text
        assert value(text, "fruit_fly_http_request_duration_seconds_count", method="GET", route="/api/health") == 1
        assert value(text, "fruit_fly_experiments_submitted_total", kind="single") == 2
        assert value(text, "fruit_fly_requests_refused_total", reason="api_key") == 1
        assert value(text, "fruit_fly_requests_refused_total", reason="rate_limit") == 1
        statuses = sum(value(text, "fruit_fly_experiments", status=s) for s in ("queued", "running", "done"))
        assert statuses == 2                                       # read from the database
        assert value(text, "fruit_fly_oldest_queued_seconds") >= 0

        for i in ids:
            wait_for(client, i)
        text = client.get("/metrics").text
        assert value(text, "fruit_fly_experiments", status="done") == 2
        assert value(text, "fruit_fly_oldest_queued_seconds") == 0
        assert value(text, "fruit_fly_simulations_total", status="done") == 2
        assert value(text, "fruit_fly_simulation_duration_seconds_count", status="done") == 2
        assert value(text, "fruit_fly_queue_wait_duration_seconds_count") == 2
        assert value(text, "fruit_fly_spikes_simulated_total") > 0
        assert value(text, "fruit_fly_simulation_speedup_ratio_count") == 2
        assert value(text, "fruit_fly_sweeps_total") == 0
        assert value(text, "fruit_fly_storage_disk_total_bytes") > 0
        assert value(text, "fruit_fly_storage_disk_available_bytes") > 0
        assert value(text, "fruit_fly_sse_connections_active") == 0
        assert value(text, "fruit_fly_recent_simulation_duration_seconds") > 0
