"""FRUIT_FLY_PARAMS_FILE: server-wide default parameters (e.g. from calibration)."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

from .conftest import CIRCUIT, DOOR, wait_for

FAST = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", "trials": 0,
        "protocol": {"stim_ms": 400, "gap_ms": 400, "settle_ms": 100}}


def make(tmp_path, params: dict) -> TestClient:
    if not (CIRCUIT / "mb_neurons.csv").exists():
        pytest.skip("no synthetic circuit")
    f = tmp_path / "calibration.json"
    f.write_text(json.dumps(params))
    return TestClient(create_app(Settings(circuit_dir=CIRCUIT, door_dir=DOOR, params_file=f,
                                          database_url=f"sqlite:///{tmp_path}/db.sqlite",
                                          storage_dir=tmp_path / "runs")))


def kc_active(client, body) -> float:
    job = client.post("/api/experiments/conditioning", json=body).json()["id"]
    done = wait_for(client, job)
    assert done["status"] == "done", done["error"]
    return done["result"]["separation"]["kc_active_plus"]


def test_file_sets_defaults_and_requests_override(tmp_path):
    with make(tmp_path, {"graded_gain": 0.0}) as client:
        assert client.get("/api/circuit").json()["default_params"] == {"graded_gain": 0.0}
        assert kc_active(client, FAST) > 0.15                                   # APL off by default
        assert kc_active(client, {**FAST, "params": {"graded_gain": 0.05}}) < 0.15   # request wins


def test_unknown_parameter_names_are_rejected(tmp_path):
    with pytest.raises(Exception, match="graded_gian"):
        with make(tmp_path, {"graded_gian": 0.0}):                              # typo in the file
            pass
    with make(tmp_path, {}) as client:
        r = client.post("/api/experiments/conditioning", json={**FAST, "params": {"learnin_rate": 1}})
        assert r.status_code == 422 and "learnin_rate" in r.text

def test_circuit_level_settings_come_from_the_file_only(tmp_path):
    with make(tmp_path, {"kc_dan": "terminal", "kc_dan_gain": 1.0}) as client:
        store = client.app.state.store
        assert store.params.kc_dan == "terminal"                       # applied when loading
        assert "kc_dan" not in client.get("/api/circuit").json()["default_params"]
        r = client.post("/api/experiments/conditioning", json={**FAST, "params": {"kc_dan": "fast"}})
        assert r.status_code == 422                                     # can't change per request
        assert kc_active(client, {**FAST, "params": {"mbon_tonic_mV": 7.1}}) >= 0
