"""API keys and rate limits on the write endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.app import apikeys
from backend.app.main import create_app
from backend.app.ratelimit import MemoryRateLimiter, RateLimited

from .conftest import FAST, make_settings, require_data, wait_for

URL = "/api/experiments/conditioning"
BODY = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST}


class Clock:
    def __init__(self, t: float = 1_000_020.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_memory_rate_limiter_windows_and_costs():
    clock = Clock()
    rl = MemoryRateLimiter(limit=3, clock=clock)
    rl.charge("a", 2)
    rl.charge("b", 3)                                   # clients are counted separately
    with pytest.raises(RateLimited) as e:
        rl.charge("a", 2)                               # 2 + 2 > 3
    assert 1 <= e.value.retry_after <= 60 and "2 already started" in str(e.value)
    rl.charge("a", 1)                                   # refused requests didn't count
    with pytest.raises(RateLimited) as e:
        rl.charge("c", 4)                               # can never fit
    assert "starts 4 experiments" in str(e.value)
    clock.t += 60
    rl.charge("a", 3)                                   # a new minute


@pytest.fixture()
def secured(tmp_path):
    require_data()
    settings = make_settings(tmp_path, require_api_key=True, max_pending=20)
    with TestClient(create_app(settings)) as c:
        yield c


def test_keys_guard_writes_only(secured):
    client = secured
    assert client.get("/api/health").json()["auth_required"] is True
    assert client.get("/api/experiments").status_code == 200          # reading stays open
    assert client.post(URL, json=BODY).status_code == 401
    r = client.post(URL, json=BODY, headers={"X-API-Key": "ff_not-a-key"})
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "X-API-Key"

    sessions = client.app.state.sessions
    key_id, key = apikeys.create(sessions, "test")
    stored = apikeys.list_keys(sessions)
    assert key not in {k.key_hash for k in stored} and stored[0].key_hash == apikeys.hash_key(key)
    r = client.post(URL, json=BODY, headers={"X-API-Key": key})
    assert r.status_code == 202, r.text
    wait_for(client, r.json()["id"])
    assert apikeys.list_keys(sessions)[0].last_used_at is not None
    assert client.delete(f"/api/experiments/{r.json()['id']}").status_code == 401
    assert client.delete(f"/api/experiments/{r.json()['id']}", headers={"X-API-Key": key}).status_code == 204

    assert apikeys.revoke(sessions, key_id) and not apikeys.revoke(sessions, key_id)
    assert client.post(URL, json=BODY, headers={"X-API-Key": key}).status_code == 401


def test_rate_limit_counts_experiments(tmp_path):
    require_data()
    settings = make_settings(tmp_path, rate_limit=3, max_pending=20)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["rate_limit_per_min"] == 3
        sweep = {"base": BODY, "parameter": "trials", "values": [1, 2], "repeats": 2}
        r = client.post("/api/sweeps", json=sweep)
        assert r.status_code == 429 and "starts 4 experiments" in r.json()["detail"]
        ids = []
        for k in range(3):
            r = client.post(URL, json={**BODY, "seed": 10 + k})
            assert r.status_code == 202, r.text
            ids.append(r.json()["id"])
        r = client.post(URL, json={**BODY, "seed": 13})
        assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 60
        assert client.post(URL, json={**BODY, "trials": 99}).status_code == 422   # still validated first
        for i in ids:
            wait_for(client, i)


def test_key_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FRUIT_FLY_DATABASE_URL", f"sqlite:///{tmp_path}/keys.db")
    assert apikeys.main(["create", "lab laptop"]) == 0
    out = capsys.readouterr().out
    key_id = out.split()[1]
    assert "key  ff_" in out and "cannot be shown again" in out
    assert apikeys.main(["list"]) == 0 and "lab laptop" in capsys.readouterr().out
    assert apikeys.main(["revoke", key_id]) == 0
    assert apikeys.main(["revoke", key_id]) == 1


def test_open_server_lets_only_the_owner_cancel_or_delete(tmp_path):
    """A public demo: anyone may submit, but only the submitter (same address)
    or a request with a valid API key may cancel or delete."""
    require_data()
    with TestClient(create_app(make_settings(tmp_path)), client=("10.0.0.1", 5000)) as alice:
        job = alice.post(URL, json={**BODY, "seed": 41}).json()["id"]
        wait_for(alice, job)
        bob = TestClient(alice.app, client=("10.0.0.2", 5000))      # same running app, another address
        assert bob.get(f"/api/experiments/{job}").status_code == 200          # reading is open
        assert bob.post(f"/api/experiments/{job}/cancel").status_code == 403
        assert bob.delete(f"/api/experiments/{job}").status_code == 403
        _, key = apikeys.create(alice.app.state.sessions, "operator")
        assert bob.post(f"/api/experiments/{job}/cancel",
                        headers={"X-API-Key": key}).status_code == 409       # allowed; already done
        assert alice.delete(f"/api/experiments/{job}").status_code == 204
        metrics = alice.get("/metrics").text
        assert 'fruit_fly_requests_refused_total{reason="not_owner"} 2.0' in metrics


def test_client_address_behind_proxies(tmp_path):
    """Only the entry our own proxy added counts; a forged one to its left is ignored."""
    require_data()
    settings = make_settings(tmp_path, rate_limit=1, proxy_hops=1)
    with TestClient(create_app(settings)) as client:
        forged = {"X-Forwarded-For": "1.1.1.1, 203.0.113.7"}         # client wrote 1.1.1.1
        assert client.post(URL, json={**BODY, "seed": 51}, headers=forged).status_code == 202
        again = {"X-Forwarded-For": "9.9.9.9, 203.0.113.7"}          # new forgery, same visitor
        assert client.post(URL, json={**BODY, "seed": 52}, headers=again).status_code == 429
        other = {"X-Forwarded-For": "203.0.113.8"}                   # a different visitor
        r = client.post(URL, json={**BODY, "seed": 53}, headers=other)
        assert r.status_code == 202
        for e in client.get("/api/experiments").json()["items"]:
            wait_for(client, e["id"])
