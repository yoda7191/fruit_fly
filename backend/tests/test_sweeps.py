"""Parameter sweeps (in-process queue)."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app

from .conftest import FAST, LEARNING, make_settings, require_data, wait_for_sweep

BASE = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST}


@pytest.fixture(scope="module")
def roomy(tmp_path_factory):
    """A client with room for whole sweeps (the shared one allows only 3 pending)."""
    require_data()
    with TestClient(create_app(make_settings(tmp_path_factory.mktemp("sweeps"), max_pending=20))) as c:
        yield c


def test_sweep_runs_and_aggregates(roomy):
    client = roomy
    r = client.post("/api/sweeps", json={"base": BASE, "parameter": "params.graded_gain",
                                          "values": [0.0, 0.05], "repeats": 2})
    assert r.status_code == 202, r.text
    created = r.json()
    assert created["total"] == 4 and created["status"] == "running"

    body = wait_for_sweep(client, created["id"])
    assert body["status"] == "done"
    assert body["counts"] == {"queued": 0, "running": 0, "done": 4, "failed": 0, "cancelled": 0}
    assert body["metrics"][0] == "performance_index"
    no_apl, apl = body["points"]
    assert no_apl["value"] == 0.0 and no_apl["done"] == 2
    # the APL result from the model: without inhibition the Kenyon cell code is dense
    assert no_apl["metrics"]["kc_active_plus"]["mean"] > 3 * apl["metrics"]["kc_active_plus"]["mean"]
    assert apl["metrics"]["kc_active_plus"]["n"] == 2
    assert apl["metrics"]["kc_active_plus"]["std"] is not None

    # members are hidden from the normal list, stored without spikes
    ids = {e["id"] for e in client.get("/api/experiments").json()["items"]}
    members = [e for e in client.get("/api/experiments", params={"include_sweeps": True}).json()["items"]
               if e["sweep_id"] == created["id"]]
    assert len(members) == 4 and not ids & {m["id"] for m in members}
    seeds = sorted(m["request"]["seed"] for m in members)
    assert seeds == [1, 1, 2, 2]
    assert client.get(f"/api/experiments/{members[0]['id']}/spikes").status_code == 409

    # CSV export
    r = client.get(f"/api/sweeps/{created['id']}/results.csv")
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4 and {row["status"] for row in rows} == {"done"}
    assert "params.graded_gain" in rows[0] and rows[0]["performance_index"] != ""

    assert created["id"] in [s["id"] for s in client.get("/api/sweeps").json()["items"]]
    assert client.delete(f"/api/sweeps/{created['id']}").status_code == 204
    assert client.get(f"/api/sweeps/{created['id']}").status_code == 404
    assert client.get(f"/api/experiments/{members[0]['id']}").status_code == 404


def test_lesion_scan(roomy):
    client = roomy
    base = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **LEARNING}
    r = client.post("/api/sweeps", json={"base": base, "parameter": "lesion",
                                          "values": ["none", "group:DAN_PPL1"], "repeats": 1})
    assert r.status_code == 202, r.text
    body = wait_for_sweep(client, r.json()["id"])
    assert body["status"] == "done" and body["values"] == ["none", "group:DAN_PPL1"]
    intact, no_ppl1 = body["points"]
    assert intact["value"] == "none" and no_ppl1["value"] == "group:DAN_PPL1"

    # each member really ran with its lesion (an ignored lesion would run intact)
    members = [m for m in client.get("/api/experiments", params={"include_sweeps": True}).json()["items"]
               if m["sweep_id"] == body["id"]]
    by_lesions = {tuple(lesion["group"] for lesion in m["request"]["lesions"]): m["id"] for m in members}
    assert set(by_lesions) == {(), ("DAN_PPL1",)}
    lesioned = client.get(f"/api/experiments/{by_lesions[('DAN_PPL1',)]}").json()["result"]["lesioned"]
    assert len(lesioned) == 6                                   # every PPL1 neuron of the synthetic circuit
    # the model result: shock learning needs PPL1 dopamine
    pi = lambda p: p["metrics"]["performance_index"]["mean"]
    assert pi(intact) > 0.2 and abs(pi(no_ppl1)) < 0.1

    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/sweeps/{body['id']}/results.csv").text)))
    assert [row["lesion"] for row in rows] == ["none", "group:DAN_PPL1"]


def test_lesion_scan_validation(roomy):
    def post(values):
        return roomy.post("/api/sweeps", json={"base": BASE, "parameter": "lesion", "values": values,
                                               "repeats": 1})
    assert post(["none", "APL"]).status_code == 422             # needs "group:" or "type:"
    assert post([0.5]).status_code == 422                       # numbers are not lesions
    assert post(["none", "none"]).status_code == 422            # duplicates
    assert post(["group:NOT_A_GROUP"]).status_code == 422       # unknown names fail before running


def test_sweep_validation(roomy):
    client = roomy
    def post(**kw):
        return client.post("/api/sweeps", json={"base": BASE, "parameter": "trials",
                                                "values": [1, 2], "repeats": 1, **kw})
    assert post(values=[1.5]).status_code == 422                     # trials must be whole
    assert "trials" in post(values=[99]).json()["detail"]             # out of range, readable
    assert post(values=[1, 1]).status_code == 422                     # duplicates
    assert post(parameter="params.nonsense").status_code == 422
    assert post(values=list(range(25)), repeats=5).status_code == 422 # > max_sweep_size (100)
    assert post(values=[]).status_code == 422
    r = client.post("/api/sweeps", json={"base": {**BASE, "odour_source": "door", "cs_plus": "octanol"},
                                          "parameter": "trials", "values": [1]})
    assert r.status_code == 422 and "3-octanol" in r.json()["detail"]["suggestions"]


def test_sweep_respects_capacity(client):
    # the session client allows 3 pending experiments; this sweep needs 4
    r = client.post("/api/sweeps", json={"base": BASE, "parameter": "trials",
                                          "values": [1, 2], "repeats": 2})
    assert r.status_code == 429