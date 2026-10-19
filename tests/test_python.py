"""Python binding tests.  Run:  python tests/test_python.py
Needs `pip install -e .`, data/synthetic (make_synthetic_mb.py) and data/raw/door
(download_door.sh); parts without data are skipped."""

import gc
import sys
from pathlib import Path

import numpy as np

import fruit_fly

ROOT = Path(__file__).resolve().parents[1]
CIRCUIT = ROOT / "data" / "synthetic"
DOOR = ROOT / "data" / "raw" / "door"
failures = 0


def check(cond, msg):
    global failures
    if not cond:
        failures += 1
        print(f"    FAIL: {msg}")


def load_net(p):
    return fruit_fly.Network.load(str(CIRCUIT / "mb_neurons.csv"), str(CIRCUIT / "mb_edges.csv"), p)


def test_types_and_lifetimes():
    p = fruit_fly.Params()
    net = load_net(p)
    check(net.positions.shape == (len(net), 3), "positions shape")
    check(net.row_ptr[-1] == net.n_synapses, "CSR consistency")
    # Network created inline and dropped: keep_alive must keep it valid
    sim = fruit_fly.Simulator(load_net(p), p, seed=1)
    gc.collect()
    orn = net.indices_in_group("ORN")[:20]
    sim.set_rates(orn, 80.0)
    sim.run(200)
    idx, t = sim.spikes()
    check(len(idx) == len(t) > 0, "spikes recorded")
    rs = fruit_fly.RateSet(orn, [50.0] * len(orn))
    a, b = rs                                          # tuple unpacking
    check(len(a) == len(b) == 20, "RateSet unpacking")


def test_conditioning_random():
    p = fruit_fly.Params()
    net = load_net(p)
    exp = fruit_fly.Experiment(net, p, fruit_fly.ProtocolConfig(), seed=7)
    exp.settle()
    r = fruit_fly.run_differential_conditioning(exp, "A", fruit_fly.random_odour(net, "odour_A"),
                                            "B", fruit_fly.random_odour(net, "odour_B"),
                                            3, fruit_fly.US.Shock)
    target = fruit_fly.dopamine_targets(net, exp.us_neurons(fruit_fly.US.Shock))
    c = fruit_fly.compartment_change(net, r, target)
    check(c.valid and c.cs_plus < -0.3 and c.cs_minus > -0.15, f"specific memory ({c.cs_plus}, {c.cs_minus})")
    check(len(exp.history) == 10, "history length")
    check(len(fruit_fly.summarize_mbons(net, r, target)) > 0, "MBON summary")
    check(isinstance(r.pre_plus.counts, np.ndarray), "counts as numpy")


def test_door():
    lib = fruit_fly.OdourLibrary.load(str(DOOR))
    check(lib.coverage("ethyl acetate") > 0.8, "coverage")
    check("3-octanol" in lib.search("octanol"), "search")
    try:
        lib.raw("not an odour")
        check(False, "unknown odour should raise")
    except (IndexError, KeyError):
        pass
    net = load_net(fruit_fly.Params())
    stim = fruit_fly.OdourStimulus(lib, net)
    idx, hz = stim.rates("3-octanol")
    check(len(idx) == len(hz) > 0 and (hz >= 0).all(), "odour rates")


if __name__ == "__main__":
    tests = [(test_types_and_lifetimes, CIRCUIT), (test_conditioning_random, CIRCUIT),
             (test_door, DOOR)]
    for fn, needs in tests:
        if not needs.exists():
            print(f"  skip {fn.__name__} (no {needs})")
            continue
        before = failures
        fn()
        print(f"  {'ok  ' if failures == before else 'FAIL'} {fn.__name__}")
    print(f"\n{failures} failed checks")
    sys.exit(1 if failures else 0)
