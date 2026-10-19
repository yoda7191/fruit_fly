"""Serving the built frontend (FRUIT_FLY_STATIC_DIR), as the Docker image does."""

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

from .conftest import CIRCUIT, DOOR


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not (CIRCUIT / "mb_neurons.csv").exists():
        pytest.skip("no synthetic circuit; run scripts/make_synthetic_mb.py")
    base = tmp_path_factory.mktemp("site")
    dist = base / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>fruit_fly</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log('app')")
    (dist / "favicon.svg").write_text("<svg/>")
    (base / "secret.txt").write_text("do not serve")       # outside the frontend folder
    settings = Settings(circuit_dir=CIRCUIT, door_dir=DOOR, static_dir=dist)
    with TestClient(create_app(settings)) as c:
        yield c


def test_index_and_spa_routes(site):
    for path in ("/", "/experiments/123", "/some/deep/page"):
        r = site.get(path)
        assert r.status_code == 200 and "<title>fruit_fly</title>" in r.text
        assert r.headers["cache-control"] == "no-cache"


def test_assets_are_cached_forever_other_files_revalidated(site):
    r = site.get("/assets/index-abc123.js")
    assert r.status_code == 200 and "console.log" in r.text
    assert "immutable" in r.headers["cache-control"]
    assert site.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_head_requests(site):
    r = site.head("/assets/index-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert site.head("/").status_code == 200


def test_api_still_works_and_unknown_api_is_404(site):
    assert site.get("/api/health").json()["status"] == "ok"
    r = site.get("/api/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_no_path_traversal(site):
    for path in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/%2e%2e/secret.txt"):
        r = site.get(path)
        assert "do not serve" not in r.text, path


def test_missing_build_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_app(Settings(circuit_dir=CIRCUIT, door_dir=DOOR, static_dir=tmp_path))


def test_api_only_without_static_dir():
    app = create_app(Settings(circuit_dir=CIRCUIT, door_dir=DOOR))
    with TestClient(app) as c:
        assert c.get("/").status_code == 404