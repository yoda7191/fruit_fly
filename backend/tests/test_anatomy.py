"""The odour catalogue, the connection explorer's endpoints and the anatomy files."""

import gzip
import os
import shutil

from fastapi.testclient import TestClient

from backend.app.main import create_app

from .conftest import CIRCUIT, make_settings, require_data


def test_odour_catalog_has_classes(client):
    items = client.get("/api/odours/catalog").json()["items"]
    by_name = {i["name"]: i for i in items}
    assert by_name["3-octanol"]["chemical_class"] == "alcohols"
    assert by_name["ethyl acetate"]["chemical_class"] == "esters"
    classes = {i["chemical_class"] for i in items}
    assert "arom" not in classes and "terpene" not in classes          # DoOR spellings merged
    assert all(0 <= i["coverage"] <= 1 for i in items)
    names = [i["name"].lower() for i in items]
    assert names == sorted(names)
    assert len(items) == client.get("/api/odours", params={"limit": 1}).json()["total"]


def test_neuron_connections(client):
    neurons = client.get("/api/circuit/neurons").json()
    mbon = neurons["group"].index("MBON")
    c = client.get(f"/api/circuit/neurons/{mbon}/connections").json()
    assert c["total_inputs"] >= len(c["inputs"]) == 200                 # the default limit
    assert {neurons["group"][p["index"]] for p in c["inputs"]} >= {"KC"}
    syn = [p["synapses"] for p in c["inputs"]]
    assert syn == sorted(syn, reverse=True)

    strong = client.get(f"/api/circuit/neurons/{mbon}/connections", params={"min_synapses": 12}).json()
    assert all(p["synapses"] >= 12 for p in strong["inputs"])
    assert strong["total_inputs"] < c["total_inputs"]
    assert len(client.get(f"/api/circuit/neurons/{mbon}/connections",
                          params={"limit": 2}).json()["inputs"]) == 2

    # dopamine coupling is listed both ways
    assert c["dopamine_from"]
    dan = c["dopamine_from"][0]
    assert neurons["group"][dan].startswith("DAN")
    assert mbon in client.get(f"/api/circuit/neurons/{dan}/connections").json()["dopamine_to"]
    assert client.get(f"/api/circuit/neurons/{neurons['count']}/connections").status_code == 404


def test_group_connectivity(client):
    rows = client.get("/api/circuit/connectivity").json()
    pairs = {(r["pre"], r["post"]): r for r in rows}
    assert pairs[("KC", "MBON")]["sign"] == "excitatory" and pairs[("KC", "MBON")]["synapses"] > 0
    assert pairs[("DAN_PPL1", "MBON")]["sign"] == "dopamine"
    fast = [r["synapses"] for r in rows if r["sign"] != "dopamine"]
    assert fast == sorted(fast, reverse=True)


def test_synthetic_circuit_has_no_anatomy(client):
    assert client.get("/api/circuit").json()["anatomy"] == {"regions": False, "morphology": False}
    assert client.get("/api/circuit/regions").status_code == 404
    assert client.get("/api/circuit/morphology").status_code == 404
    table = client.get("/api/circuit/neurons").json()
    assert table["flywire_id"] == table["root_id"]


def test_anatomy_files_are_served(tmp_path):
    require_data()
    circuit = tmp_path / "circuit"
    circuit.mkdir()
    for f in ("mb_neurons.csv", "mb_edges.csv"):
        shutil.copy(CIRCUIT / f, circuit / f)
    (circuit / "brain_regions.json").write_text('{"units":"nm","regions":[]}')
    (circuit / "mb_morphology.bin").write_bytes(b"FFMORPH2" + bytes(8))
    with TestClient(create_app(make_settings(tmp_path / "app", circuit_dir=circuit))) as c:
        assert c.get("/api/circuit").json()["anatomy"] == {"regions": True, "morphology": True}
        r = c.get("/api/circuit/regions")
        assert r.status_code == 200 and r.json()["regions"] == []
        r = c.get("/api/circuit/morphology")
        assert r.status_code == 200 and r.content.startswith(b"FFMORPH2")
        assert r.headers["content-type"] == "application/octet-stream"
        assert "etag" in r.headers                          # browsers revalidate instead of refetching

        # a prebuilt gzip copy is sent as is (not compressed again on every request)
        body = b"FFMORPH2" + bytes(5000)
        (circuit / "mb_morphology.bin").write_bytes(body)
        (circuit / "mb_morphology.bin.gz").write_bytes(gzip.compress(body))
        r = c.get("/api/circuit/morphology", headers={"Accept-Encoding": "gzip"})
        assert r.headers["content-encoding"] == "gzip" and r.content == body   # httpx decompresses
        assert int(r.headers["content-length"]) < len(body)
        r = c.get("/api/circuit/morphology", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in r.headers and r.content == body
        assert r.headers["vary"].count("Accept-Encoding") == 1
        # an outdated copy (older than the file) is ignored
        (circuit / "mb_morphology.bin.gz").write_bytes(gzip.compress(b"stale"))
        os.utime(circuit / "mb_morphology.bin.gz", (0, 0))
        assert c.get("/api/circuit/morphology", headers={"Accept-Encoding": "gzip"}).content == body
