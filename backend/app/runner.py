"""Run one conditioning experiment and turn the C++ results into plain data.

This is the only module that drives the simulator. It runs in a worker
thread; the C++ calls release the GIL, so the web server stays responsive.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

import fruit_fly

from .model import ModelStore
from .schemas import ConditioningRequest

ProgressFn = Callable[[int, int], None]     # (presentations done, total)

US_FROM_NAME = {"none": fruit_fly.US.None_, "shock": fruit_fly.US.Shock, "reward": fruit_fly.US.Reward}
US_BY_NAME = {"shock": fruit_fly.US.Shock, "reward": fruit_fly.US.Reward}
US_NAME = {fruit_fly.US.None_: "none", fruit_fly.US.Shock: "shock", fruit_fly.US.Reward: "reward"}


@dataclass
class RunOutput:
    result: dict                    # matches schemas.ExperimentResult
    spike_neurons: np.ndarray       # int32, sorted by time
    spike_times: np.ndarray         # float32 ms


def finite_or_none(x: float) -> float | None:
    return float(x) if x is not None and math.isfinite(x) else None


def _treves_rolls(counts: np.ndarray) -> float | None:
    if len(counts) == 0:
        return None
    c = np.asarray(counts, dtype=np.float64)
    sum_c = np.sum(c)
    sum_sq = np.sum(c ** 2)
    if sum_sq == 0:
        return 0.0
    return float((sum_c ** 2) / (len(c) * sum_sq))


def build_params(req: ConditioningRequest, defaults: dict | None = None) -> fruit_fly.Params:
    """fruit_fly defaults <- server defaults (FRUIT_FLY_PARAMS_FILE) <- the request's overrides."""
    p = fruit_fly.Params()
    for name, value in {**(defaults or {}), **req.params.model_dump(exclude_none=True)}.items():
        setattr(p, name, value)
    return p


def build_protocol(req: ConditioningRequest) -> fruit_fly.ProtocolConfig:
    cfg = fruit_fly.ProtocolConfig()
    for name, value in req.protocol.model_dump().items():
        setattr(cfg, name, value)
    return cfg


def build_behavior(req: ConditioningRequest) -> fruit_fly.BehaviorConfig:
    cfg = fruit_fly.BehaviorConfig()
    cfg.sharpness = req.behavior.sharpness
    cfg.flies = req.behavior.flies
    cfg.seed = req.seed
    return cfg


def choice_dict(c: fruit_fly.TMazeChoice) -> dict:
    return {"drive_plus": finite_or_none(c.drive_plus), "drive_minus": finite_or_none(c.drive_minus),
            "p_plus": c.p_plus, "preference": c.preference}


def odour_inputs(store: ModelStore, req: ConditioningRequest):
    """({slot: (name, rates)}, baseline, door info). Slots: A = cs_plus, B = cs_minus, C/D = extras."""
    names = {"A": req.cs_plus, "B": req.cs_minus, **req.extra_odours}
    if req.odour_source == "random":
        net = store.network
        return ({slot: (name, fruit_fly.random_odour(net, name)) for slot, name in names.items()},
                fruit_fly.RateSet(), None)

    if store.stimulus is None:
        raise LookupError("odour data not loaded")
    resolved = {slot: store.resolve_odour(name) for slot, name in names.items()}
    plus, minus = resolved[req.readout.plus], resolved[req.readout.minus]
    info = {
        "coverage": {n: store.odour_coverage(n) for n in resolved.values()},
        "input_similarity": finite_or_none(store.library.similarity(plus, minus)),
    }
    return ({slot: (n, store.stimulus.rates(n)) for slot, n in resolved.items()},
            store.stimulus.baseline(), info)


def build_steps(req: ConditioningRequest) -> list[fruit_fly.ProtocolStep]:
    steps = []
    for st in req.effective_steps():
        s = fruit_fly.ProtocolStep()
        s.phase = st.phase
        s.odour = st.odour or ""
        s.us = US_FROM_NAME[st.us]
        s.odour_ms = -1.0 if st.odour_ms is None else st.odour_ms
        s.us_onset_ms = st.us_onset_ms
        s.us_ms = -1.0 if st.us_ms is None else st.us_ms
        s.gap_ms = -1.0 if st.gap_ms is None else st.gap_ms
        s.repeat = st.repeat
        steps.append(s)
    return steps


def run_experiment(store: ModelStore, req: ConditioningRequest,
                   progress: ProgressFn | None = None) -> RunOutput:
    net = store.network
    params = build_params(req, store.default_params)
    protocol = build_protocol(req)
    odours, baseline, door_info = odour_inputs(store, req)
    us = US_BY_NAME[req.us]
    steps = build_steps(req)
    lesioned = store.lesion_indices(req.lesions)

    exp = fruit_fly.Experiment(net, params, protocol, req.seed)
    if lesioned:
        exp.simulator.silence(lesioned)
    exp.set_baseline(baseline)
    exp.settle()
    weights_before = exp.simulator.plastic_weights()
    made = fruit_fly.run_protocol(exp, steps, {slot: rates for slot, (_, rates) in odours.items()}, progress)
    ro = req.readout
    n_us = sum(1 for p in made if p.us != fruit_fly.US.None_)
    r = fruit_fly.conditioning_readout(made, ro.plus, ro.minus, ro.before, ro.after, us, n_us,
                                   weights_before, exp.simulator.plastic_weights(), exp.spontaneous_hz)

    # ---------------------------------------------------------- analysis
    sep = fruit_fly.pattern_separation(net, r.pre_plus.counts, r.pre_minus.counts)
    target = fruit_fly.dopamine_targets(net, exp.us_neurons(us))
    change = fruit_fly.compartment_change(net, r, target)
    behavior = fruit_fly.tmaze_test(net, r, build_behavior(req))

    ratio = r.weights_after / net.plastic_w0
    post = net.plastic_post
    mbon_weights = []
    for m in np.unique(post):
        if store.group[m] != "MBON":             # e.g. APL with apl_plasticity
            continue
        mbon_weights.append({
            "index": int(m),
            "cell_type": store.cell_type[m],
            "weight_ratio": float(ratio[post == m].mean()),
        })

    # ------------------------------------------------ expanded metrics
    w_min = float(params.w_min_frac)
    hist_counts, bin_edges = np.histogram(ratio, bins=10, range=(0.0, 1.0))
    bins = [
        {"bin_start": round(float(bin_edges[i]), 2),
         "bin_end": round(float(bin_edges[i + 1]), 2),
         "count": int(hist_counts[i])}
        for i in range(len(hist_counts))
    ]
    weight_stats = {
        "mean": finite_or_none(np.mean(ratio)),
        "std": finite_or_none(np.std(ratio)),
        "min": finite_or_none(np.min(ratio)),
        "max": finite_or_none(np.max(ratio)),
        "median": finite_or_none(np.median(ratio)),
        "p10": finite_or_none(np.percentile(ratio, 10)),
        "p90": finite_or_none(np.percentile(ratio, 90)),
        "floor_fraction": finite_or_none(float(np.mean(ratio <= (w_min + 1e-4)))),
        "histogram": bins,
    }

    grp = store.group.astype(str)
    kc_idx = np.flatnonzero(grp == "KC")
    mbon_idx = np.flatnonzero(grp == "MBON")
    dan_idx = np.flatnonzero(np.char.startswith(grp, "DAN"))
    target_mbon_idx = np.flatnonzero((grp == "MBON") & (np.asarray(target) > 0))
    if len(target_mbon_idx) == 0:
        target_mbon_idx = mbon_idx

    names = {slot: name for slot, (name, _) in odours.items()}

    learning_curve = []
    trial_counter: dict[str, int] = {}
    for p in made:
        if p.phase == "training":
            slot = p.label
            trial_counter[slot] = trial_counter.get(slot, 0) + 1
            cnts = np.asarray(p.counts)
            mbon_spikes = float(cnts[target_mbon_idx].mean()) if len(target_mbon_idx) else 0.0
            mbon_all = float(cnts[mbon_idx].mean()) if len(mbon_idx) else 0.0
            kc_active = int((cnts[kc_idx] > 0).sum()) if len(kc_idx) else 0
            dan_spikes = float(cnts[dan_idx].mean()) if len(dan_idx) else 0.0
            learning_curve.append({
                "trial": trial_counter[slot],
                "slot": slot,
                "odour": names.get(slot, slot),
                "us": US_NAME.get(p.us, "none"),
                "mbon_spikes": round(mbon_spikes, 2),
                "mbon_all_spikes": round(mbon_all, 2),
                "kc_active_count": kc_active,
                "dan_spikes": round(dan_spikes, 2),
            })

    pop_groups = []
    for gname in ("ORN", "ALPN", "KC", "MBON", "DAN_PPL1", "DAN_PAM", "APL"):
        g_idx = np.flatnonzero(grp == gname)
        if len(g_idx) == 0:
            continue
        dur_pre_p = max(0.001, r.pre_plus.duration_ms / 1000.0)
        dur_post_p = max(0.001, r.post_plus.duration_ms / 1000.0)
        dur_pre_m = max(0.001, r.pre_minus.duration_ms / 1000.0)
        dur_post_m = max(0.001, r.post_minus.duration_ms / 1000.0)
        pop_groups.append({
            "group": gname,
            "pre_plus_hz": round(float(np.asarray(r.pre_plus.counts)[g_idx].mean() / dur_pre_p), 2),
            "post_plus_hz": round(float(np.asarray(r.post_plus.counts)[g_idx].mean() / dur_post_p), 2),
            "pre_minus_hz": round(float(np.asarray(r.pre_minus.counts)[g_idx].mean() / dur_pre_m), 2),
            "post_minus_hz": round(float(np.asarray(r.post_minus.counts)[g_idx].mean() / dur_post_m), 2),
        })

    post_p_mbons = np.asarray(r.post_plus.counts)[mbon_idx].astype(float) if len(mbon_idx) else np.zeros(0)
    post_m_mbons = np.asarray(r.post_minus.counts)[mbon_idx].astype(float) if len(mbon_idx) else np.zeros(0)
    denom = post_p_mbons + post_m_mbons
    active_mbons = denom > 0
    mbon_discrim = float(np.mean(np.abs(post_m_mbons[active_mbons] - post_p_mbons[active_mbons]) / denom[active_mbons])) if np.any(active_mbons) else 0.0

    kc_cnts_pre_p = np.asarray(r.pre_plus.counts)[kc_idx] if len(kc_idx) else np.zeros(0)
    kc_cnts_pre_m = np.asarray(r.pre_minus.counts)[kc_idx] if len(kc_idx) else np.zeros(0)
    population_stats = {
        "groups": pop_groups,
        "kc_sparseness": {
            "active_plus_count": int((kc_cnts_pre_p > 0).sum()),
            "active_minus_count": int((kc_cnts_pre_m > 0).sum()),
            "total_kc": int(len(kc_idx)),
            "treves_rolls_plus": finite_or_none(_treves_rolls(kc_cnts_pre_p)),
            "treves_rolls_minus": finite_or_none(_treves_rolls(kc_cnts_pre_m)),
        },
        "mbon_discrimination": round(mbon_discrim, 4),
    }

    prediction = {
        "expected_shock": finite_or_none(exp.simulator.expected_shock),
        "expected_reward": finite_or_none(exp.simulator.expected_reward),
    }
    def label(slot_key: str) -> str | None:              # "A+C" -> "octanol + benzaldehyde"
        parts = slot_key.split("+")
        return " + ".join(names[s] for s in parts) if all(s in names for s in parts) else None

    timeline = [{
        "label": label(p.label) or "US",
        "slot": p.label if label(p.label) else None,
        "us": US_NAME[p.us],
        "phase": p.phase,
        "t_start_ms": p.t_start_ms,
        "t_end_ms": p.t_start_ms + p.duration_ms,
        "us_start_ms": finite_or_none(p.us_start_ms),
        "us_end_ms": finite_or_none(p.us_end_ms),
    } for p in made]
    readout_after_ms = next(p.t_start_ms for p in made if p.phase == ro.after and p.us == fruit_fly.US.None_)

    neurons, times = exp.simulator.spikes()
    order = np.argsort(times, kind="stable")      # already chronological; guarantees it
    neurons, times = neurons[order].astype(np.int32), times[order].astype(np.float32)

    result = {
        "separation": {
            "pn_correlation": finite_or_none(sep.pn_correlation),
            "kc_correlation": finite_or_none(sep.kc_correlation),
            "kc_active_plus": sep.kc_active_plus,
            "kc_active_minus": sep.kc_active_minus,
            "kc_shared": sep.kc_shared,
        },
        "mbons": [
            {"cell_type": s.cell_type, "n": s.n, "us_target": s.us_target,
             "pre_plus": s.pre_plus, "post_plus": s.post_plus,
             "pre_minus": s.pre_minus, "post_minus": s.post_minus}
            for s in fruit_fly.summarize_mbons(net, r, target)
        ],
        "compartment_change": {
            "valid": change.valid,
            "cs_plus": change.cs_plus if change.valid else None,
            "cs_minus": change.cs_minus if change.valid else None,
        },
        "mean_weight_ratio": finite_or_none(fruit_fly.mean_weight_ratio(net, r.weights_after)),
        "mbon_weights": mbon_weights,
        "timeline": timeline,
        "duration_ms": exp.simulator.time_ms,
        "n_spikes": int(len(times)),
        "coverage": door_info["coverage"] if door_info else None,
        "input_similarity": door_info["input_similarity"] if door_info else None,
        "readout": ro.model_dump(),
        "readout_after_ms": readout_after_ms,
        "odours": names,
        "lesioned": lesioned,
        "weight_stats": weight_stats,
        "learning_curve": learning_curve,
        "population_stats": population_stats,
        "prediction": prediction,
        "behavior": {
            "valid": behavior.valid,
            "valenced_mbons": behavior.valenced_mbons,
            "naive": choice_dict(behavior.naive),
            "trained": choice_dict(behavior.trained),
            "learned_drive": finite_or_none(behavior.learned_drive),
            "performance_index": finite_or_none(behavior.performance_index),
            "flies": behavior.flies,
            "sampled_performance_index": finite_or_none(behavior.sampled_performance_index),
        },
    }
    return RunOutput(result=result, spike_neurons=neurons, spike_times=times)