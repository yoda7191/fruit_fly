"""Generate a small fake mushroom body in the same CSV format as
extract_mb_circuit.py, for testing the simulator without FlyWire data.

The STRUCTURE follows the biology (glomeruli, ~6 PN inputs per KC, one APL,
DAN->MBON compartments). The NUMBERS are invented. Never report results from
this data as findings about the fly.

Usage: python scripts/make_synthetic_mb.py [out_dir=data/synthetic]
"""

import csv
import random
import sys
from pathlib import Path

rng = random.Random(0)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/synthetic")
out.mkdir(parents=True, exist_ok=True)

neurons, edges = [], []
next_id = 720575940600000000          # FlyWire-looking 18-digit IDs


# Transmitter per group, written to the nt_type column like the extractor does.
GROUP_NT = {"ORN": "ACH", "ALPN": "ACH", "KC": "ACH", "APL": "GABA", "DPM": "SER",
            "DAN_PPL1": "DA", "DAN_PAM": "DA"}


def add(group, cell_type, n, center, spread=3000.0, nt=None):
    global next_id
    ids = []
    for _ in range(n):
        pos = [c + rng.gauss(0, spread) for c in center]
        neurons.append([next_id, group, cell_type, "right", *[round(v) for v in pos],
                        nt or GROUP_NT.get(group, "")])
        ids.append(next_id)
        next_id += 1
    return ids


def connect(pre, post, syn, nt, sign):
    edges.append([pre, post, syn, nt, sign])


# ---- antennal lobe: real glomerulus names (those DoOR has data for),
#      20 ORNs + 2 PNs each. ORN cell types follow FlyWire: "ORN_<glomerulus>".
glomeruli = """D DA1 DA2 DA3 DA4l DA4m DC1 DC2 DC3 DC4 DL1 DL2d DL2v DL3 DL4 DL5 DM1 DM2
DM3 DM4 DM5 DM6 DP1l DP1m V VA1d VA1v VA2 VA3 VA4 VA5 VA6 VA7l VC1 VC2 VC3 VC4 VC5
VL1 VL2a VL2p VM1 VM2 VM3 VM4 VM5d VM5v VM7d VM7v""".split()
pns = []
for g in glomeruli:
    orn_ids = add("ORN", f"ORN_{g}", 20, (140000, 60000, 90000))
    pn_ids = add("ALPN", f"{g}_PN", 2, (140000, 65000, 95000))
    pns += pn_ids
    for o in orn_ids:
        for p in pn_ids:
            connect(o, p, rng.randint(8, 14), "ACH", 1)

# ---- Kenyon cells: 1000 KCs, each samples ~6 random PNs (the "claws")
kcs = add("KC", "KCg-m", 1000, (170000, 70000, 110000), 6000)
for k in kcs:
    for p in rng.sample(pns, rng.randint(5, 7)):
        connect(p, k, rng.randint(14, 20), "ACH", 1)

# ---- APL: excited by all KCs, inhibits all KCs (GABA)
apl = add("APL", "APL", 1, (175000, 72000, 112000))[0]
for k in kcs:
    connect(k, apl, 3, "ACH", 1)
    connect(apl, k, 20, "GABA", -1)

# ---- MBONs: 20 cells in 10 types; each samples ~70% of KCs
# Transmitters follow the fly's layout (Aso et al. 2014a): the punishment (PPL1)
# compartments hold approach-promoting cholinergic/GABAergic MBONs, the reward
# (PAM) compartments mostly avoidance-promoting glutamatergic ones. That is why
# shock, by weakening approach outputs, teaches avoidance.
MBON_NT = {0: ("GABA", -1), 1: ("ACH", 1), 2: ("ACH", 1), 3: ("GABA", -1),
           4: ("GLUT", -1), 5: ("GLUT", -1), 6: ("GLUT", -1), 7: ("GLUT", -1),
           8: ("GLUT", -1), 9: ("ACH", 1)}
mbons = []
for t in range(10):
    nt, sign = MBON_NT[t]
    for _ in range(2):
        m = add("MBON", f"MBON{t + 1:02d}", 1, (190000, 80000, 120000), nt=nt)[0]
        mbons.append((m, t))
        for k in kcs:
            if rng.random() < 0.7:
                connect(k, m, rng.randint(8, 14), "ACH", 1)

# ---- DANs: PPL1 (punishment) own compartments 0-3, PAM (reward) own 4-9
ppl1 = add("DAN_PPL1", "PPL101", 6, (195000, 60000, 125000))
pam = add("DAN_PAM", "PAM01", 20, (185000, 95000, 118000))
for m, t in mbons:
    for d in (ppl1 if t < 4 else pam):
        connect(d, m, rng.randint(10, 20), "DA", 0)
    # a little MBON -> DAN feedback, as seen in the real connectome
    for d in rng.sample(ppl1 + pam, 2):
        connect(m, d, rng.randint(5, 10), *MBON_NT[t])

# ---- DPM: one cell reciprocally connected with KCs (serotonin -> sign 0 here)
dpm = add("DPM", "DPM", 1, (178000, 74000, 114000))[0]
for k in rng.sample(kcs, 500):
    connect(k, dpm, 2, "ACH", 1)
    connect(dpm, k, 4, "SER", 0)

with open(out / "mb_neurons.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["root_id", "group", "cell_type", "side", "x", "y", "z", "nt_type"])
    w.writerows(neurons)
with open(out / "mb_edges.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pre_root_id", "post_root_id", "syn_count", "nt_type", "sign"])
    w.writerows(edges)
print(f"wrote {len(neurons)} neurons, {len(edges)} edges to {out}/")