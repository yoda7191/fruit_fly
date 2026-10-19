"""Extract the olfactory / mushroom body circuit from the FlyWire v783 tables.

Circuit (per the fly literature):
    ORN -> ALPN -> KC -> MBON          (odour pathway)
    DAN -> KC/MBON compartments        (reward = PAM, punishment = PPL1)
    APL <-> KC                         (global inhibition -> sparse KC code)

Usage:
    python scripts/extract_mb_circuit.py --explore      # inspect labels first
    python scripts/extract_mb_circuit.py                # extract circuit
    python scripts/extract_mb_circuit.py --side right   # one hemisphere only
    python scripts/extract_mb_circuit.py --min-syn 5    # drop weak connections

Connections come from FlyWire's unthresholded table by default. The smaller
connections.csv.gz keeps only rows (neuron pair x neuropil) with >= 5
synapses; that removes most Kenyon cell -> MBON input, because each KC makes
only a few synapses on each MBON (in FlyWire v783, 42% of all synapses are in
rows below 5). --min-syn applies a threshold to each pair's total instead.

Outputs (data/processed/):
    mb_neurons.csv   root_id, group, cell_type, side, x, y, z, nt_type
    mb_edges.csv     pre_root_id, post_root_id, syn_count, nt_type, sign
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

# Fast-synapse sign by presynaptic neurotransmitter (as in Shiu et al. 2024).
# Glutamate is mostly inhibitory in the fly central brain (GluCl receptors; in the
# antennal lobe shown by Liu & Wilson 2013). MBONs and DANs also express excitatory
# NMDA receptors (Li et al. 2020), so measured exceptions go in known_synapse_signs.csv.
# DA/SER/OCT are modulatory: sign 0 here; dopamine is handled by the
# plasticity rule in the simulator, not as a fast current.
NT_SIGN = {"ACH": 1, "GABA": -1, "GLUT": -1, "DA": 0, "SER": 0, "OCT": 0}

# Groups whose transmitter is established experimentally; these override the
# image-based predictions (Eckstein et al. 2024), which are noisy per synapse.
#   ORN, KC: acetylcholine (KCs: Barnstedt et al. 2016)
#   APL: GABA (Liu & Davis 2009)
#   PAM, PPL1: dopamine (they are defined as dopaminergic clusters)
# MBONs and PNs differ between cell types, and keep their per-neuron prediction.
KNOWN_NT = {"ORN": "ACH", "KC": "ACH", "APL": "GABA", "DAN_PAM": "DA", "DAN_PPL1": "DA"}

# Cell types whose transmitter has been checked against the literature, with
# sources. They override the prediction. Add a row only with a citable source.
KNOWN_TYPE_NT_FILE = Path(__file__).with_name("known_transmitters.csv")
# Connections between cell types whose sign was measured and differs from the one the
# transmitter implies (e.g. a glutamatergic MBON exciting a DAN through NMDA receptors).
# Add a row only with a citable source.
KNOWN_SIGN_FILE = Path(__file__).with_name("known_synapse_signs.csv")

GROUP_ORDER = ["ORN", "ALLN", "ALPN", "KC", "APL", "DPM", "MBON", "DAN_PAM", "DAN_PPL1"]


# ---------------------------------------------------------------- loading

def load_tables(raw: Path, connections: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cls = pd.read_csv(raw / "classification.csv.gz", dtype={"root_id": "int64"})
    types = pd.read_csv(raw / "consolidated_cell_types.csv.gz", dtype={"root_id": "int64"})
    neurons = cls.merge(types, on="root_id", how="left")

    # One best label per neuron: consolidated type > cell_type > hemibrain_type.
    label = pd.Series(pd.NA, index=neurons.index, dtype="object")
    for col in ["primary_type", "cell_type", "hemibrain_type"]:
        if col in neurons:
            label = label.fillna(neurons[col])
    neurons["label"] = label.fillna("").astype(str)

    conns = pd.read_csv(raw / connections, dtype={"neuropil": "category", "nt_type": "category"})
    conns = conns.rename(columns={"pre_pt_root_id": "pre_root_id",
                                  "post_pt_root_id": "post_root_id"})
    coords = pd.read_csv(raw / "coordinates.csv.gz")
    return neurons, conns, coords


def text(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna("").astype(str) if col in df else pd.Series("", index=df.index)


# ---------------------------------------------------------------- explore

def explore(neurons: pd.DataFrame) -> None:
    """Print the labels that matter, so the selection rules can be checked."""
    pat = re.compile(r"kenyon|^kc|mbon|pam|ppl1|apl|dpm|alpn|olfactory|orn", re.I)
    for col in ["super_class", "class", "sub_class"]:
        if col in neurons:
            vc = text(neurons, col).value_counts()
            hits = vc[[bool(pat.search(v)) for v in vc.index]]
            print(f"\n== {col} (matching MB keywords) ==\n{hits.to_string()}")
    vc = neurons["label"].value_counts()
    for prefix in ["KC", "MBON", "PAM", "PPL1", "APL", "DPM", "ORN"]:
        hits = vc[vc.index.str.upper().str.startswith(prefix)]
        print(f"\n== labels starting with {prefix}: {len(hits)} types, "
              f"{hits.sum()} neurons ==\n{hits.head(12).to_string()}")


# ---------------------------------------------------------------- select

def assign_groups(neurons: pd.DataFrame) -> pd.Series:
    lab = neurons["label"].str.upper()
    klass = text(neurons, "class").str.lower()

    g = pd.Series(pd.NA, index=neurons.index, dtype="object")
    rules = [
        ("KC",       klass.str.contains("kenyon") | lab.str.startswith("KC")),
        ("MBON",     klass.eq("mbon") | lab.str.startswith("MBON")),
        ("DAN_PAM",  lab.str.startswith("PAM")),
        ("DAN_PPL1", lab.str.startswith("PPL1")),
        ("APL",      lab.eq("APL")),
        ("DPM",      lab.eq("DPM")),
        ("ALPN",     klass.eq("alpn")),
        ("ALLN",     klass.eq("alln")),       # antennal lobe local neurons
        ("ORN",      lab.str.startswith("ORN") | klass.eq("olfactory")),
    ]
    for name, mask in rules:          # first matching rule wins
        g = g.mask(g.isna() & mask, name)
    return g


def prune_input_side(neurons: pd.DataFrame, conns: pd.DataFrame) -> pd.DataFrame:
    """Keep only PNs that actually feed KCs, ORNs that feed those PNs, and the
    antennal lobe local neurons connected (either way) to those ORNs or PNs."""
    ids = lambda grp: set(neurons.loc[neurons.group == grp, "root_id"])
    kcs = ids("KC")
    pn_to_kc = set(conns.loc[conns.pre_root_id.isin(ids("ALPN"))
                             & conns.post_root_id.isin(kcs), "pre_root_id"])
    orn_to_pn = set(conns.loc[conns.pre_root_id.isin(ids("ORN"))
                              & conns.post_root_id.isin(pn_to_kc), "pre_root_id"])
    al = pn_to_kc | orn_to_pn
    lns = ids("ALLN")
    ln_kept = set(conns.loc[conns.pre_root_id.isin(lns) & conns.post_root_id.isin(al), "pre_root_id"]) \
        | set(conns.loc[conns.post_root_id.isin(lns) & conns.pre_root_id.isin(al), "post_root_id"])
    keep = (~neurons.group.isin(["ALPN", "ORN", "ALLN"])
            | neurons.root_id.isin(al | ln_kept))
    return neurons[keep]


def transmitters(conns: pd.DataFrame, mb: pd.DataFrame) -> pd.Series:
    """Each neuron's predicted transmitter, from its output synapses across the
    WHOLE brain. Must be computed before edges are restricted to the circuit:
    output neurons (MBONs) send most of their synapses outside the mushroom
    body, so in-circuit edges alone would often leave them with no transmitter,
    and hence no approach/avoid valence.

    Transmitter is a property of the cell type, so neurons of one type pool
    their evidence: the type's transmitter is the one carrying most of all its
    neurons' synapses. Per neuron, the predictions disagree for a few types
    (e.g. one MBON05 predicted cholinergic, the other glutamatergic). Neurons
    without a type use their own synapses."""
    out = conns[conns.pre_root_id.isin(set(mb.root_id)) & conns.nt_type.notna()]
    per_nt = out.groupby(["pre_root_id", "nt_type"], as_index=False, observed=True).syn_count.sum()
    label = mb.set_index("root_id").label
    per_nt["unit"] = per_nt.pre_root_id.map(label).where(lambda t: t != "", None)
    per_nt["unit"] = per_nt.unit.fillna("id:" + per_nt.pre_root_id.astype(str))
    votes = per_nt.groupby(["unit", "nt_type"], as_index=False, observed=True).syn_count.sum()
    best = (votes.sort_values(["unit", "syn_count", "nt_type"], ascending=[True, False, True])
                 .drop_duplicates("unit").set_index("unit").nt_type)
    unit = label.where(label != "", "id:" + label.index.astype(str))
    return unit.map(best)


# ---------------------------------------------------------------- regional APL

APL_REGIONS = ("CA", "PED", "VL", "ML")           # calyx, peduncle, vertical lobe, medial lobe
UNIT_ID_BASE = 9_000_000_000_000_000_000           # above every FlyWire id (~7.2e17), below 2**63


def mb_region(neuropil: str) -> str | None:
    """"MB_ML_L" -> "ML"; anything outside the mushroom body -> None."""
    m = re.match(r"MB_(CA|PED|VL|ML)(_|$)", str(neuropil))
    return m.group(1) if m else None


def split_apl(mb: pd.DataFrame, edges: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace each APL by one unit per mushroom body region (calyx, peduncle,
    vertical lobe, medial lobe) that receives and gives only the synapses in that
    region. APL's inhibition is spatially localised: local stimulation inhibits
    the nearby compartments, so APL can inhibit different compartments
    differently (Amin et al. 2020, eLife 9:e56954). As one point neuron, every
    Kenyon cell's input reached every APL target, e.g. silencing MBON-g5b'2a even
    at rest. The units are not coupled: this is the fully local extreme, the
    point neuron the fully global one.

    `edges` has one row per (pre, post, neuropil). Synapses labelled outside the
    MB (neighbouring neuropils such as CRE or PLP; KCs never leave the MB, so these
    are boundary labels) go to the region where the same partner's other synapses
    with this APL lie, else to the APL's main region. Units keep group, cell type
    ("APL"), side and position; flywire_id keeps the parent's id.
    """
    apl = sorted(mb.root_id[mb.group.eq("APL")])
    if not apl:
        return mb, edges
    pre_apl, post_apl = edges.pre_root_id.isin(apl), edges.post_root_id.isin(apl)
    if (pre_apl & post_apl).any():
        raise ValueError("APL -> APL synapses: not expected, and not handled")
    e = edges[pre_apl | post_apl].copy()
    e["apl"] = e.pre_root_id.where(pre_apl, e.post_root_id)
    e["partner"] = e.post_root_id.where(pre_apl, e.pre_root_id)
    e["region"] = e.neuropil.map(mb_region)
    labelled = e.dropna(subset=["region"])
    def majority(keys):
        t = labelled.groupby([*keys, "region"]).syn_count.sum().reset_index()
        return t.sort_values("syn_count").drop_duplicates(keys, keep="last").set_index(keys).region
    by_pair, by_apl = majority(["apl", "partner"]), majority(["apl"])
    missing = e.region.isna()
    e.loc[missing, "region"] = [by_pair.get((a, p), by_apl[a])
                                for a, p in zip(e.apl[missing], e.partner[missing])]
    unit_of = {(a, r): UNIT_ID_BASE + 10 * i + j
               for i, a in enumerate(apl) for j, r in enumerate(APL_REGIONS)}
    unit = pd.Series([unit_of[(a, r)] for a, r in zip(e.apl, e.region)], index=e.index)
    e.loc[pre_apl[e.index], "pre_root_id"] = unit[pre_apl[e.index]]
    e.loc[post_apl[e.index], "post_root_id"] = unit[post_apl[e.index]]
    out_edges = pd.concat([edges[~(pre_apl | post_apl)], e[edges.columns]], ignore_index=True)

    used = set(unit)
    rows = []
    for (a, r), uid in unit_of.items():
        if uid in used:
            row = mb[mb.root_id.eq(a)].iloc[0].copy()
            row["root_id"], row["flywire_id"], row["region"] = uid, a, r
            rows.append(row)
    units = pd.DataFrame(rows)
    share = e.groupby("region").syn_count.sum() / e.syn_count.sum()
    print("APL split into regional units: " + ", ".join(f"{r} {share.get(r, 0):.0%}" for r in APL_REGIONS)
          + f" of its synapses ({int(missing.sum())} rows outside the MB assigned by partner)")
    return pd.concat([mb[~mb.group.eq("APL")], units], ignore_index=True), out_edges


def attach_coords(neurons: pd.DataFrame, coords: pd.DataFrame) -> pd.DataFrame:
    # 'position' is a string like "[123 456 789]"; take the first point per neuron.
    first = coords.drop_duplicates("root_id")[["root_id", "position"]]
    xyz = first["position"].astype(str).str.findall(r"-?\d+\.?\d*")
    first = first.assign(x=xyz.str[0].astype(float),
                         y=xyz.str[1].astype(float),
                         z=xyz.str[2].astype(float))
    return neurons.merge(first.drop(columns="position"), on="root_id", how="left")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    ap.add_argument("--side", choices=["left", "right", "both"], default="both")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--connections", default="connections_no_threshold.csv.gz",
                    help="connection table in --raw (connections.csv.gz is thresholded at 5 per row)")
    ap.add_argument("--min-syn", type=int, default=1,
                    help="keep circuit connections with at least this many synapses (pair total)")
    ap.add_argument("--mbon-mbon", choices=["all", "in-mb"], default="in-mb",
                    help="MBON -> MBON synapses to keep: all, or only those inside the MB "
                         "neuropils (on MBON dendrites; outside, most contact MBON axons)")
    ap.add_argument("--apl", choices=["global", "regional"], default="global",
                    help="APL as one point neuron (global inhibition) or one unit per MB region "
                         "(calyx, peduncle, vertical lobe, medial lobe; localised inhibition)")
    ap.add_argument("--dan-input", choices=["all", "dendritic"], default="dendritic",
                    help="synapses onto dopamine neurons to keep: all, or only those outside the "
                         "MB neuropils (on DAN dendrites; inside, they contact DAN axons). "
                         "KC -> DAN synapses are always kept: the model treats them as axonal itself")
    args = ap.parse_args()

    neurons, conns, coords = load_tables(args.raw, args.connections)
    if args.explore:
        explore(neurons)
        return

    neurons["group"] = assign_groups(neurons)
    mb = neurons[neurons.group.notna()].copy()
    if args.side != "both" and "side" in mb:
        mb = mb[mb.side.eq(args.side)]
    mb = prune_input_side(mb, conns)
    mb = attach_coords(mb, coords)

    # Edges inside the circuit; the same pair can appear once per neuropil,
    # so sum synapses across neuropils.
    ids = set(mb.root_id)
    predicted = mb.root_id.map(transmitters(conns, mb)).fillna("")
    known_type = pd.read_csv(KNOWN_TYPE_NT_FILE).set_index("cell_type").nt_type
    by_type = mb.label.map(known_type)
    changed = mb[by_type.notna() & (by_type != predicted)]
    for t, grp in changed.groupby("label"):
        print(f"transmitter of {t}: predicted {sorted(set(predicted[grp.index]))}, "
              f"set to {known_type[t]} ({KNOWN_TYPE_NT_FILE.name})")
    mb["nt_type"] = mb.group.map(KNOWN_NT).fillna(by_type).fillna(predicted)
    edges = conns[conns.pre_root_id.isin(ids) & conns.post_root_id.isin(ids)]
    if args.mbon_mbon == "in-mb":
        # Typical MBONs receive input on dendrites in the MB lobes (Aso et al. 2014a); their axons run
        # outside (CRE, SMP, SIP), where ~64% of MBON -> MBON synapses sit. Those are
        # mostly axo-axonic and shape release downstream, not spiking, so a point
        # neuron should not integrate them. Atypical MBONs with dendrites outside
        # the MB lose some real input under this rule.
        mbon = set(mb.root_id[mb.group.eq("MBON")])
        axonal = (edges.pre_root_id.isin(mbon) & edges.post_root_id.isin(mbon)
                  & ~edges.neuropil.astype(str).str.startswith("MB_"))
        edges = edges[~axonal]
    if args.dan_input == "dendritic":
        # DAN dendrites lie outside the MB (SMP, SIP, CRE ...); their axons tile the lobes
        # (Aso et al. 2014a). MBON feedback reaches "the dendrites of DANs" from MBON axon
        # termini outside the MB; inside the lobes, MBONs make only "axo-axonal synapses onto
        # a subset of DANs" (Li et al. 2020). Synapses onto DANs inside the MB are thus onto
        # axon terminals: like KC -> DAN (kc_dan = "terminal"), they shape release, not
        # spiking. As spike-driving input they let odours alone fire punishment DANs
        # (MBON-a3 -> PPL1-a3, 91 of its 118 synapses in the vertical lobe), so the model
        # learned from odour exposure without any US.
        dan = set(mb.root_id[mb.group.isin(["DAN_PPL1", "DAN_PAM"])])
        kc = set(mb.root_id[mb.group.eq("KC")])
        on_axon = (edges.post_root_id.isin(dan) & ~edges.pre_root_id.isin(kc)
                   & edges.neuropil.astype(str).str.startswith("MB_"))
        print(f"synapses onto DAN axons (inside the MB) left out: {int(edges.syn_count[on_axon].sum())}")
        edges = edges[~on_axon]
    mb["flywire_id"] = mb.root_id
    if args.apl == "regional":
        mb, edges = split_apl(mb, edges)
    edges = (edges.groupby(["pre_root_id", "post_root_id"], as_index=False)
                  .agg(syn_count=("syn_count", "sum")))
    edges = edges[edges.syn_count >= args.min_syn]
    # Dale's principle: every connection uses its presynaptic neuron's transmitter.
    # Per-synapse predictions are noisy; taking them per edge made ~5% of edges
    # change sign (e.g. GABAergic APL "exciting" some Kenyon cells, which then
    # fired tonically without any odour).
    edges["nt_type"] = edges.pre_root_id.map(mb.set_index("root_id").nt_type).astype(str)
    edges["sign"] = edges.nt_type.map(NT_SIGN).fillna(0).astype(int)
    label = mb.set_index("root_id").label
    for row in pd.read_csv(KNOWN_SIGN_FILE).itertuples():
        hit = edges.pre_root_id.map(label).eq(row.pre_type) & edges.post_root_id.map(label).eq(row.post_type)
        edges.loc[hit, "sign"] = row.sign
        print(f"sign of {row.pre_type} -> {row.post_type}: {int(row.sign):+d} on {hit.sum()} connections "
              f"({KNOWN_SIGN_FILE.name})")

    args.out.mkdir(parents=True, exist_ok=True)
    cols = ["root_id", "group", "label", "side", "x", "y", "z", "nt_type", "flywire_id", "region"]
    mb[[c for c in cols if c in mb]].rename(columns={"label": "cell_type"}) \
        .to_csv(args.out / "mb_neurons.csv", index=False)
    edges.to_csv(args.out / "mb_edges.csv", index=False)

    # ---- sanity report
    counts = mb.group.value_counts().reindex(GROUP_ORDER, fill_value=0)
    print("Neurons per group:\n" + counts.to_string())
    for grp, n in counts.items():
        if n == 0:
            print(f"  WARNING: no {grp} neurons matched — run --explore and fix the rules")

    gid = mb.set_index("root_id").group
    e = edges.assign(pre=edges.pre_root_id.map(gid), post=edges.post_root_id.map(gid))
    flow = e.pivot_table(index="pre", columns="post", values="syn_count",
                         aggfunc="sum", fill_value=0)
    print("\nSynapses between groups (rows = pre, cols = post):")
    print(flow.reindex(index=GROUP_ORDER, columns=GROUP_ORDER, fill_value=0).to_string())

    kc_in = e[e.post.eq("KC") & e.pre.eq("ALPN")].groupby("post_root_id").size()
    if len(kc_in):
        print(f"\nPN inputs per KC: median {kc_in.median():.0f} "
              f"(literature: ~5-7 claws per KC)")
    print(f"\nWrote {len(mb)} neurons and {len(edges)} edges to {args.out}/ "
          f"(from {args.connections}, pairs with >= {args.min_syn} synapses)")


if __name__ == "__main__":
    main()