"""Spike stores: the S3 store (chunked by time) against the local one.

S3 is mocked with moto; set FRUIT_FLY_TEST_S3_ENDPOINT (e.g. a MinIO at
http://127.0.0.1:9000, with AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) to also
run an experiment end to end against a real S3-compatible server.
"""

import os
import uuid

import numpy as np
import pytest

from backend.app.spikes import LocalSpikeStore, S3SpikeStore

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")


def recording(n=20_000, t_max=9_500.0, seed=0):
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0, t_max, n)).astype(np.float32)
    return rng.integers(0, 500, n).astype(np.int32), times


@pytest.fixture()
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="spikes")
        yield client


def test_s3_store_matches_local(s3, tmp_path):
    neurons, times = recording()
    local, remote = LocalSpikeStore(tmp_path), S3SpikeStore("spikes", client=s3)
    eid = uuid.uuid4().hex
    for store in (local, remote):
        assert not store.exists(eid)
        store.save(eid, neurons, times)
        assert store.exists(eid)
    mask = np.zeros(500, bool)
    mask[::3] = True
    rng = np.random.default_rng(1)
    for _ in range(25):                                  # windows across chunk boundaries
        t0 = float(rng.uniform(-500, 9000))
        t1 = t0 + float(rng.uniform(1, 2500))
        for m, cap in ((None, 10**9), (mask, 10**9), (None, 50)):
            a = local.window(eid, t0, t1, m, cap)
            b = remote.window(eid, t0, t1, m, cap)
            assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and a[2] == b[2]


def test_s3_window_downloads_only_overlapping_chunks(s3):
    neurons, times = recording()
    store = S3SpikeStore("spikes", client=s3)
    eid = uuid.uuid4().hex
    store.save(eid, neurons, times)
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="spikes")["Contents"]]
    assert len(keys) == 10 + 1                           # 10 one-second chunks + meta.json
    fetched = []
    real_get = s3.get_object
    s3.get_object = lambda **kw: fetched.append(kw["Key"]) or real_get(**kw)
    store.window(eid, 2100.0, 3900.0, None, 10**9)
    chunks = sorted(k.rsplit("/", 1)[1] for k in fetched if k.endswith(".npz"))
    assert chunks == ["c000002.npz", "c000003.npz"]


def test_s3_resave_delete_and_ids(s3):
    store = S3SpikeStore("spikes", prefix="runs", client=s3)
    eid = uuid.uuid4().hex
    store.save(eid, *recording(t_max=9_500.0))
    store.save(eid, *recording(n=10, t_max=500.0))       # shorter: old chunks must go
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="spikes")["Contents"]]
    assert sorted(k.rsplit("/", 1)[1] for k in keys) == ["c000000.npz", "meta.json"]
    assert all(k.startswith(f"runs/{eid}/") for k in keys)
    assert len(store.window(eid, 0, 1000, None, 100)[0]) == 10
    store.delete(eid)
    assert not store.exists(eid) and "Contents" not in s3.list_objects_v2(Bucket="spikes")
    store.save(eid, np.zeros(0, np.int32), np.zeros(0, np.float32))   # empty recordings work
    assert store.exists(eid) and len(store.window(eid, 0, 1000, None, 10)[0]) == 0
    with pytest.raises(ValueError):
        store.save("../../etc", *recording(n=1))


def test_missing_bucket_fails_at_startup(s3):
    store = S3SpikeStore("no-such-bucket", client=s3)
    with pytest.raises(RuntimeError, match="no-such-bucket.*not reachable"):
        store.check()
    S3SpikeStore("spikes", client=s3).check()            # an existing bucket passes


@pytest.mark.skipif(not os.environ.get("FRUIT_FLY_TEST_S3_ENDPOINT"),
                    reason="set FRUIT_FLY_TEST_S3_ENDPOINT (and AWS credentials) for a real S3/MinIO")
def test_experiment_spikes_through_real_s3(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    from .conftest import FAST, make_settings, require_data, wait_for

    require_data()
    endpoint = os.environ["FRUIT_FLY_TEST_S3_ENDPOINT"]
    bucket = f"fruit-fly-test-{uuid.uuid4().hex[:8]}"
    boto3.client("s3", endpoint_url=endpoint).create_bucket(Bucket=bucket)
    settings = make_settings(tmp_path, spike_store="s3", s3_bucket=bucket, s3_endpoint=endpoint)
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/experiments/conditioning",
                        json={"odour_source": "random", "cs_plus": "A", "cs_minus": "B", **FAST})
        eid = r.json()["id"]
        assert wait_for(client, eid)["status"] == "done"
        w = client.get(f"/api/experiments/{eid}/spikes", params={"t0_ms": 0, "t1_ms": 2000}).json()
        assert len(w["neurons"]) > 0 and all(0 <= t < 2000 for t in w["times_ms"])
        assert client.delete(f"/api/experiments/{eid}").status_code == 204
        assert "Contents" not in boto3.client("s3", endpoint_url=endpoint).list_objects_v2(Bucket=bucket)
