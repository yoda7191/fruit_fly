"""Shared fixtures.

Needs data/synthetic (scripts/make_synthetic_mb.py) and data/raw/door
(scripts/download_door.sh); tests are skipped if they're missing. Every app
gets its own temporary SQLite database and spike folder.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import REPO_ROOT, Settings, sqlite_url
from backend.app.main import create_app

CIRCUIT = REPO_ROOT / "data" / "synthetic"
DOOR = REPO_ROOT / "data" / "raw" / "door"

# Short protocol for tests that don't measure learning (~1 s per experiment).
FAST = {"trials": 1, "protocol": {"stim_ms": 400, "gap_ms": 600, "settle_ms": 100}}

# Shortest protocol that still produces clear, seed-independent learning
# (CS+ about -60%, CS- within +-10% on the synthetic circuit; ~4 s).
LEARNING = {"trials": 2, "protocol": {"stim_ms": 1000, "gap_ms": 1000, "settle_ms": 100}}


def require_data() -> None:
    if not (CIRCUIT / "mb_neurons.csv").exists():
        pytest.skip("no synthetic circuit; run scripts/make_synthetic_mb.py")
    if not (DOOR / "door_response_matrix.csv").exists():
        pytest.skip("no DoOR data; run scripts/download_door.sh")


def make_settings(folder: Path, **overrides) -> Settings:
    """Settings with a private SQLite database and spike folder under `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    values = dict(circuit_dir=CIRCUIT, door_dir=DOOR, max_workers=2,
                  database_url=sqlite_url(folder / "test.db"), storage_dir=folder / "runs")
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    require_data()
    settings = make_settings(tmp_path_factory.mktemp("api"), max_pending=3)
    with TestClient(create_app(settings)) as c:      # `with` runs startup/shutdown
        yield c


def wait_for(client, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/experiments/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.2)
    raise TimeoutError(f"experiment {job_id} did not finish in {timeout}s")


def wait_for_sweep(client, sweep_id: str, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/sweeps/{sweep_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.3)
    raise TimeoutError(f"sweep {sweep_id} did not finish in {timeout}s")