"""API tests.  Run from the repository root:  pytest backend/tests -q"""

import time

from .conftest import FAST, LEARNING, wait_for


# ------------------------------------------------------------------ meta + circuit

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["odours_loaded"] is True


def test_large_responses_are_gzipped(client):
    r = client.get("/api/circuit/neurons", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.json()["count"] > 0                          # client decompresses transparently
    small = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers        # below minimum_size


def test_progress_is_reported_while_running(client):
    job_id = client.post("/api/experiments/conditioning", json={
        "odour_source": "random", "cs_plus": "A", "cs_minus": "B", "trials": 4,
        "protocol": {"stim_ms": 300, "gap_ms": 300, "settle_ms": 100}}).json()["id"]
    seen = set()
    while True:
        body = client.get(f"/api/experiments/{job_id}").json()
        if body["progress"]:
            seen.add(body["progress"]["done"])
            assert body["progress"]["total"] == 12
        if body["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert body["status"] == "done"
    assert len(seen) >= 3 and max(seen) == 12             # intermediate values observed


def test_circuit_summary(client):
    body = client.get("/api/circuit").json()
    assert body["neurons"] == sum(body["groups"].values())
    assert body["groups"]["KC"] > 0
    assert body["mbons_with_ppl1_dopamine"] > 0


def test_neuron_table_is_columnar_and_js_safe(client):
    body = client.get("/api/circuit/neurons").json()
    n = body["count"]
    for column in ("root_id", "group", "cell_type", "x", "y", "z"):
        assert len(body[column]) == n
    assert all(isinstance(r, str) for r in body["root_id"])   # > 2**53, must not be a number
    assert body["bounds"] is not None


# ------------------------------------------------------------------ odours

def test_odour_search_and_paging(client):
    body = client.get("/api/odours", params={"search": "octanol"}).json()
    names = [i["name"] for i in body["items"]]
    assert "3-octanol" in names
    page = client.get("/api/odours", params={"limit": 5, "offset": 5}).json()
    assert len(page["items"]) == 5 and page["total"] > 500


def test_odour_detail_case_insensitive(client):
    body = client.get("/api/odours/detail", params={"name": "ETHYL ACETATE"}).json()
    assert body["name"] == "ethyl acetate"
    assert len(body["glomeruli"]) > 40
    assert any(g["response"] is None for g in client.get(
        "/api/odours/detail", params={"name": "4-methylcyclohexanol"}).json()["glomeruli"])


def test_unknown_odour_suggests(client):
    r = client.get("/api/odours/detail", params={"name": "octanol"})
    assert r.status_code == 404
    assert "3-octanol" in r.json()["detail"]["suggestions"]


def test_similarity(client):
    same = client.get("/api/odours/similarity", params={"a": "ethyl acetate", "b": "ethyl acetate"})
    assert abs(same.json()["similarity"] - 1.0) < 1e-9


# ------------------------------------------------------------------ validation

def test_rejects_bad_requests(client):
    url = "/api/experiments/conditioning"
    assert client.post(url, json={"trials": 99}).status_code == 422
    assert client.post(url, json={"cs_plus": "3-octanol", "cs_minus": "3-OCTANOL"}).status_code == 422
    r = client.post(url, json={"cs_plus": "octanol"})
    assert r.status_code == 422 and "suggestions" in r.json()["detail"]
    assert client.post(url, json={"params": {"graded_gain": -1}}).status_code == 422
    assert client.get("/api/experiments/nope").status_code == 404


# ------------------------------------------------------------------ experiments

def test_conditioning_end_to_end(client):
    r = client.post("/api/experiments/conditioning",
                    json={"cs_plus": "ethyl acetate", "cs_minus": "benzaldehyde", **LEARNING})
    assert r.status_code == 202
    job_id = r.json()["id"]
    body = wait_for(client, job_id)
    assert body["status"] == "done", body["error"]
    assert body["progress"] == {"done": 8, "total": 8}    # 2 pre + 2 trials x 2 + 2 post

    res = body["result"]
    assert res["coverage"]["ethyl acetate"] > 0.8
    assert len(res["timeline"]) == 8                     # 2 pre + 2 trials x 2 + 2 post
    assert [t["phase"] for t in res["timeline"]] == ["pre"] * 2 + ["training"] * 4 + ["post"] * 2
    assert res["timeline"][2]["us"] == "shock"
    cc = res["compartment_change"]
    assert cc["valid"]
    assert cc["cs_plus"] < -0.3                          # punished odour: response drops
    assert cc["cs_minus"] > -0.15                        # other odour: roughly unchanged
    b = res["behavior"]
    assert b["performance_index"] > 0.3                  # flies learn to avoid CS+
    assert b["trained"]["drive_plus"] < b["naive"]["drive_plus"]
    assert b["flies"] == 100 and -1 <= b["sampled_performance_index"] <= 1
    assert any(w["weight_ratio"] < 1.0 for w in res["mbon_weights"])

    # spikes: windowing, group filter, truncation
    everything = {"t0_ms": 0, "t1_ms": res["duration_ms"] + 1}
    capped = client.get(f"/api/experiments/{job_id}/spikes", params=everything).json()
    assert capped["truncated"] == (res["n_spikes"] > 200_000)    # default cap
    win = client.get(f"/api/experiments/{job_id}/spikes",
                     params={**everything, "max_spikes": 2_000_000}).json()
    assert win["count"] == res["n_spikes"] and not win["truncated"]
    assert win["times_ms"] == sorted(win["times_ms"])
    kc = client.get(f"/api/experiments/{job_id}/spikes",
                    params=[("t0_ms", 0), ("t1_ms", 5000), ("group", "KC")]).json()
    groups = client.get("/api/circuit/neurons").json()["group"]
    assert kc["count"] > 0 and all(groups[i] == "KC" for i in kc["neurons"])
    small = client.get(f"/api/experiments/{job_id}/spikes",
                       params={"t0_ms": 0, "t1_ms": 5000, "max_spikes": 10}).json()
    assert small["count"] == 10 and small["truncated"]
    bad = client.get(f"/api/experiments/{job_id}/spikes", params={"t0_ms": 5, "t1_ms": 1})
    assert bad.status_code == 422


def test_random_odours_reward_and_overrides(client):
    body = wait_for(client, client.post("/api/experiments/conditioning", json={
        "odour_source": "random", "cs_plus": "A", "cs_minus": "B", "us": "reward",
        "params": {"graded_gain": 0.0}, **FAST}).json()["id"])
    assert body["status"] == "done", body["error"]
    res = body["result"]
    assert res["coverage"] is None
    assert res["timeline"][2]["us"] == "reward"
    assert res["separation"]["kc_active_plus"] > 0.15      # APL off -> dense KC code


def test_list_delete_and_capacity(client):
    """max_pending = 3 in this client: a 4th unfinished experiment is refused."""
    for job in client.get("/api/experiments").json()["items"]:      # tidy up finished jobs
        if job["status"] in ("done", "failed", "cancelled"):
            assert client.delete(f"/api/experiments/{job['id']}").status_code == 204
    # long enough to still be running a few milliseconds later, when the 4th is submitted
    slow = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", "trials": 2,
            "protocol": {"stim_ms": 500, "gap_ms": 500, "settle_ms": 100}}
    # different seeds: identical requests would share one run
    ids = [client.post("/api/experiments/conditioning", json={**slow, "seed": 100 + k}).json()["id"]
           for k in range(3)]
    over = client.post("/api/experiments/conditioning", json={**slow, "seed": 103})
    assert over.status_code == 429                          # max_experiments = 3, none finished
    assert client.delete(f"/api/experiments/{ids[0]}").status_code in (204, 409)
    listed = [j["id"] for j in client.get("/api/experiments").json()["items"]]
    assert listed[0] == ids[-1]                              # newest first
    for i in ids:
        wait_for(client, i)

def test_neuron_detail_and_activity(client):
    neurons = client.get("/api/circuit/neurons").json()
    mbon = neurons["group"].index("MBON")
    d = client.get(f"/api/circuit/neurons/{mbon}").json()
    assert d["group"] == "MBON" and d["root_id"] == neurons["root_id"][mbon]
    assert d["input_synapses"] > 0 and d["inputs"][0]["group"] == "KC"         # KCs drive MBONs
    assert d["inputs"][0]["sign"] == "excitatory" and d["inputs"][0]["neurons"] > 1
    syns = [p["synapses"] for p in d["inputs"]]
    assert syns == sorted(syns, reverse=True)
    assert len(client.get(f"/api/circuit/neurons/{mbon}", params={"limit": 1}).json()["inputs"]) == 1
    assert client.get(f"/api/circuit/neurons/{neurons['count']}").status_code == 404

    job = client.post("/api/experiments/conditioning", json={
        "odour_source": "random", "cs_plus": "A", "cs_minus": "B", "trials": 1,
        "protocol": {"stim_ms": 400, "gap_ms": 400, "settle_ms": 100}}).json()["id"]
    done = wait_for(client, job)
    orn = neurons["group"].index("ORN")
    a = client.get(f"/api/experiments/{job}/neurons/{orn}").json()
    assert len(a["presentations"]) == len(done["result"]["timeline"])
    assert sum(p["spikes"] for p in a["presentations"]) <= a["total_spikes"]
    first = a["presentations"][0]
    assert abs(first["rate_hz"] - first["spikes"] / ((first["t_end_ms"] - first["t_start_ms"]) / 1000)) < 1e-9
    assert client.get(f"/api/experiments/{job}/neurons/{neurons['count']}").status_code == 404
