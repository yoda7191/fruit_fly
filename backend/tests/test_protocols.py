"""Custom protocols, presets and lesions through the API."""

from .conftest import wait_for

URL = "/api/experiments/conditioning"
# short presentations keep these tests fast; they check mechanics, not learning strength
FASTP = {"stim_ms": 400, "gap_ms": 400, "settle_ms": 100}
RANDOM = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", "protocol": FASTP}


def run(client, body: dict) -> dict:
    r = client.post(URL, json=body)
    assert r.status_code == 202, r.text
    done = wait_for(client, r.json()["id"])
    assert done["status"] == "done", done["error"]
    return done["result"]


def test_presets_are_listed_and_valid(client):
    presets = client.get("/api/protocols").json()
    names = {p["name"] for p in presets}
    assert {"differential", "extinction", "reversal", "second_order", "backward_pairing"} <= names
    for p in presets:
        assert p["in_flies"] and p["in_model"] and p["steps"]
        body = {**RANDOM, "steps": p["steps"], "readout": p["readout"], "params": p["params"],
                "extra_odours": {s: f"odour_{s}" for s in p["extra_odour_slots"]},
                # mechanics only: very short presentations keep six presets fast
                "protocol": {"stim_ms": 100, "gap_ms": 50, "settle_ms": 0}}
        # validation only: a bad preset would fail here with 422
        r = client.post(URL, json={**body, "steps": p["steps"][:1] + p["steps"]})
        assert r.status_code == 202, (p["name"], r.text)
        wait_for(client, r.json()["id"])


def test_custom_steps_timeline_and_backward_us_window(client):
    steps = [{"phase": "pre", "odour": "A"}, {"phase": "pre", "odour": "B"},
             {"phase": "training", "odour": "A", "us": "shock", "us_onset_ms": -600, "us_ms": 400},
             {"phase": "training", "us": "shock", "us_ms": 200},                 # US alone
             {"phase": "post", "odour": "A"}, {"phase": "post", "odour": "B"}]
    res = run(client, {**RANDOM, "steps": steps, "params": {"plasticity_rule": "timing"}})
    tl = res["timeline"]
    assert [t["phase"] for t in tl] == ["pre", "pre", "training", "training", "post", "post"]
    back = tl[2]
    assert back["us"] == "shock" and back["us_end_ms"] < back["t_start_ms"]   # shock before odour
    assert abs(back["t_start_ms"] - back["us_start_ms"] - 600) < 1e-6
    assert tl[3]["label"] == "US" and tl[3]["slot"] is None
    assert res["readout_after_ms"] == tl[4]["t_start_ms"]
    assert res["odours"] == {"A": "A", "B": "B"}


def test_compound_steps_and_expected_us(client):
    steps = [{"phase": "pre", "odour": "C"}, {"phase": "pre", "odour": "B"},
             {"phase": "compound", "odour": "A+C", "us": "shock"},
             {"phase": "post", "odour": "C"}, {"phase": "post", "odour": "B"}]
    res = run(client, {**RANDOM, "steps": steps, "extra_odours": {"C": "C"}, "params": {"pe_us": True},
                       "readout": {"plus": "C", "minus": "B", "before": "pre", "after": "post"}})
    compound = res["timeline"][2]
    assert compound["slot"] == "A+C" and compound["label"] == "A + C"
    assert res["behavior"]["valid"]


def test_protocol_validation_errors(client):
    def err(**extra):
        r = client.post(URL, json={**RANDOM, **extra})
        assert r.status_code == 422, r.text
        return str(r.json()["detail"])
    assert "extra_odours has no C" in err(steps=[{"phase": "pre", "odour": "C"}])
    assert "needs a US-free presentation" in err(steps=[{"phase": "pre", "odour": "A"}])
    assert "one kind of US" in err(steps=[{"phase": "x", "odour": "A", "us": "reward"}])
    assert "odour, a US, or both" in err(steps=[{"phase": "x"}])
    assert "names a slot twice" in err(steps=[{"phase": "x", "odour": "A+A"}])
    assert "extra_odours has no C" in err(steps=[{"phase": "x", "odour": "A+C"}])
    assert "limit" in err(steps=[{"phase": "pre", "odour": "A", "repeat": 50}] * 5)
    assert "different odours" in err(readout={"plus": "A", "minus": "A"})
    assert "matches no neurons" in err(lesions=[{"cell_type": "NOT_A_TYPE"}])
    assert "exactly one" in err(lesions=[{"group": "APL", "cell_type": "APL"}])


def test_lesions(client):
    options = client.get("/api/circuit/lesion-options").json()
    assert "APL" in options["groups"] and "MBON01" in options["cell_types"]
    # APL silenced -> dense Kenyon cell code (as with graded_gain = 0)
    res = run(client, {**RANDOM, "trials": 0, "lesions": [{"group": "APL"}]})
    assert len(res["lesioned"]) == 1
    assert res["separation"]["kc_active_plus"] > 0.15
    # PPL1 dopamine neurons silenced -> shock teaches nothing (Claridge-Chang et al. 2009)
    body = {"odour_source": "random", "cs_plus": "A", "cs_minus": "B", "trials": 2,
            "protocol": {"stim_ms": 1000, "gap_ms": 1000, "settle_ms": 100}}
    normal = run(client, body)
    lesioned = run(client, {**body, "lesions": [{"group": "DAN_PPL1"}]})
    assert normal["behavior"]["performance_index"] > 0.3        # clear learning in the control
    assert abs(lesioned["behavior"]["performance_index"]) < 0.1
    assert abs(lesioned["mean_weight_ratio"] - 1.0) < 1e-6           # no weight changed at all