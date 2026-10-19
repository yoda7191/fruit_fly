"""Check the model against published findings, and calibrate its free parameters.

    python -m fruit_fly.validation --circuit data/processed --door data/raw/door \\
        --calibrate --params-out data/calibration.json --out docs/validation-flywire.md

Each check runs the model the way the cited experiment was run and compares one
number with a target. "Pass" means the model reproduces the qualitative finding
at that threshold; it is not a fit to the data. Checks that the model is known
not to reproduce are still run and reported (see CIRCUIT.md).

Calibration sets the two parameters with no direct measurement:
  graded_gain   (APL inhibition) so the median odour activates ~7% of Kenyon cells
  learning_rate so 3 forward pairings reduce the CS+ response by ~60%
Validation then runs with the calibrated values.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np

import fruit_fly

# Well-measured DoOR odours (>= 75% of glomeruli), chemically varied.
ODOURS = ["ethyl acetate", "pentyl acetate", "2,3-butanedione", "butyric acid", "phenethyl alcohol",
         "propanoic acid", "acetic acid", "2-heptanone", "benzaldehyde", "1-octen-3-ol",
         "ethyl butyrate", "isopentyl acetate", "1-hexanol", "geranyl acetate", "E2-hexenal", "acetone"]

KC_ACTIVE_TARGET = 0.07           # Honegger et al. 2011; Turner et al. 2008: ~5-10%
CS_PLUS_CHANGE_TARGET = -0.60     # moderate, unsaturated learning after 3 pairings


@dataclass
class Check:
    name: str
    finding: str                  # what flies do
    reference: str
    measured: str
    target: str
    passed: bool | None           # None = reported, not judged
    note: str = ""


@dataclass
class Settings:
    trials: int = 3
    stim_ms: float = 1000.0
    gap_ms: float = 2000.0
    n_odours: int = 16
    n_pairs: int = 5
    acquisition: tuple[int, ...] = (0, 1, 2, 3, 5)
    seed: int = 1

    @classmethod
    def quick(cls) -> "Settings":
        return cls(stim_ms=600.0, gap_ms=1000.0, n_odours=6, n_pairs=3, acquisition=(0, 1, 3))


@dataclass
class Model:
    net: fruit_fly.Network
    stim: fruit_fly.OdourStimulus
    lib: fruit_fly.OdourLibrary
    settings: Settings
    params: dict = field(default_factory=dict)          # overrides of fruit_fly.Params defaults
    evoked_shock: dict = field(default_factory=dict)    # set by measurable_odours()

    @classmethod
    def load(cls, circuit: Path, door: Path, settings: Settings, params: dict | None = None) -> "Model":
        p = fruit_fly.Params()                  # structural parameters (e.g. excluded_pairs)
        for k, v in (params or {}).items():     # act when the network is built
            setattr(p, k, v)
        net = fruit_fly.Network.load(str(circuit / "mb_neurons.csv"), str(circuit / "mb_edges.csv"), p)
        lib = fruit_fly.OdourLibrary.load(str(door))
        return cls(net, fruit_fly.OdourStimulus(lib, net), lib, settings, dict(params or {}))

    def odours(self) -> list[str]:
        available = set(self.lib.names())
        return [o for o in ODOURS if o in available][: self.settings.n_odours]

    def _params(self, overrides: dict | None) -> fruit_fly.Params:
        p = fruit_fly.Params()
        for k, v in {**self.params, **(overrides or {})}.items():
            setattr(p, k, v)
        return p

    def _experiment(self, overrides=None, lesion_groups=(), seed=None) -> fruit_fly.Experiment:
        cfg = fruit_fly.ProtocolConfig()
        cfg.stim_ms, cfg.gap_ms = self.settings.stim_ms, self.settings.gap_ms
        exp = fruit_fly.Experiment(self.net, self._params(overrides), cfg,
                               self.settings.seed if seed is None else seed)
        silenced = [i for g in lesion_groups for i in self.net.indices_in_group(g)]
        if silenced:
            exp.simulator.silence(silenced)
        exp.set_baseline(self.stim.baseline())
        exp.settle()
        return exp

    def responses(self, odours: list[str], overrides=None) -> dict[str, np.ndarray]:
        """Spike counts per neuron for each odour, presented once, without learning."""
        exp = self._experiment({**(overrides or {}), "plasticity_on": False})
        return {o: exp.present(o, self.stim.rates(o)).counts for o in odours}

    def extinction(self, plus: str, minus: str, *, repeats: int = 6, overrides=None) -> tuple[float, float]:
        """Train (3 shock pairings), then present the CS+ alone `repeats` times.
        Returns the performance index after training and after extinction."""
        exp = self._experiment(overrides)

        def step(phase, odour, shock=False, repeat=1):
            s = fruit_fly.ProtocolStep()
            s.phase, s.odour, s.repeat = phase, odour, repeat
            if shock:
                s.us = fruit_fly.US.Shock
            return s

        steps = [step("pre", "A"), step("pre", "B")]
        for _ in range(self.settings.trials):
            steps += [step("training", "A", True), step("training", "B")]
        steps += [step("trained", "A"), step("trained", "B"),
                  step("extinction", "A", repeat=repeats), step("post", "A"), step("post", "B")]
        w0 = exp.simulator.plastic_weights()
        made = fruit_fly.run_protocol(exp, steps, {"A": self.stim.rates(plus), "B": self.stim.rates(minus)})
        w1 = exp.simulator.plastic_weights()
        pis = []
        for after in ("trained", "post"):
            r = fruit_fly.conditioning_readout(made, "A", "B", "pre", after, fruit_fly.US.Shock,
                                               self.settings.trials, w0, w1, exp.spontaneous_hz)
            b = fruit_fly.tmaze_test(self.net, r)
            pis.append(b.performance_index if b.valid else math.nan)
        return pis[0], pis[1]

    def _onto_mbon(self) -> np.ndarray:
        """Mask over plastic synapses: those onto MBONs (with apl_plasticity, some are onto APL)."""
        return np.asarray(self.net.group)[self.net.plastic_post] == "MBON"

    def measurable_odours(self, odours: list[str], repeats: int = 3) -> list[str]:
        """Odours whose evoked MBON response (spikes minus spontaneous) is positive in both
        the shock and the reward compartments, by more than 3x its trial-to-trial SD.
        Learning in those compartments can only be measured for such odours: an odour
        that doesn't excite them has nothing for depression to reduce."""
        exp = self._experiment({"plasticity_on": False})
        spont = np.asarray(exp.spontaneous_hz) if len(exp.spontaneous_hz) else 0.0
        mbons = np.zeros(len(self.net), bool)
        mbons[self.net.indices_in_group("MBON")] = True
        target = {u: np.asarray(fruit_fly.dopamine_targets(self.net, exp.us_neurons(u)), bool) & mbons
                  for u in (fruit_fly.US.Shock, fruit_fly.US.Reward)}
        keep = []
        self.evoked_shock = {}                   # odour -> evoked spikes in the shock compartments
        for o in odours:
            reps = [np.asarray(exp.present(o, self.stim.rates(o)).counts) - spont * self.settings.stim_ms / 1000
                    for _ in range(repeats)]
            noise = 3 * float(np.std([r[mbons].sum() for r in reps]))
            mean = np.mean(reps, axis=0)
            self.evoked_shock[o] = float(mean[target[fruit_fly.US.Shock]].sum())
            if all(mean[t].sum() > max(noise, 0.0) for t in target.values()):
                keep.append(o)
        return keep

    def blocking(self, a: str, b: str, x: str, *, pretrain: int = 10, compound: int = 3,
                 overrides=None) -> dict:
        """Kamin blocking. Pretrain A with shock (control: A without shock), then train the
        compound A+X with shock; B is the unpaired CS- throughout. Returns X's performance
        index (X vs B, pre -> post) and the fraction of synaptic weight lost by the KCs only
        X activates, in the shock compartments, for the blocking and control groups."""
        out = {}
        for group, pre_us in (("blocked", True), ("control", False)):
            exp = self._experiment(overrides)

            def step(phase, odour, shock=False, repeat=1):
                s = fruit_fly.ProtocolStep()
                s.phase, s.odour, s.repeat = phase, odour, repeat
                if shock:
                    s.us = fruit_fly.US.Shock
                return s

            steps = [step("pre", "X"), step("pre", "B"), step("pre", "A")]
            for _ in range(pretrain):
                steps += [step("pretraining", "A", pre_us), step("pretraining", "B")]
            for _ in range(compound):
                steps += [step("compound", "A+X", True), step("compound", "B")]
            steps += [step("post", "X"), step("post", "B")]
            odours = {"A": self.stim.rates(a), "B": self.stim.rates(b), "X": self.stim.rates(x)}
            w0 = exp.simulator.plastic_weights()
            made = fruit_fly.run_protocol(exp, steps, odours)
            w1 = exp.simulator.plastic_weights()
            r = fruit_fly.conditioning_readout(made, "X", "B", "pre", "post", fruit_fly.US.Shock,
                                               compound, w0, w1, exp.spontaneous_hz)
            beh = fruit_fly.tmaze_test(self.net, r)
            kc_a = np.asarray(made[2].counts)[self.net.plastic_pre] > 0
            kc_x = np.asarray(made[0].counts)[self.net.plastic_pre] > 0
            target = np.asarray(fruit_fly.dopamine_targets(self.net, exp.us_neurons(fruit_fly.US.Shock)),
                                bool)[self.net.plastic_post] & self._onto_mbon()
            sel = kc_x & ~kc_a & target
            lost = 1.0 - w1[sel].sum() / self.net.plastic_w0[sel].sum() if sel.any() else math.nan
            out[group] = {"pi": beh.performance_index if beh.valid else math.nan, "synapses_lost": lost}
        return out

    def condition(self, plus: str, minus: str, *, trials: int | None = None, us: str = "shock",
                  overrides=None, lesion_groups=(), backward: bool = False, seed=None) -> dict:
        """Differential conditioning; returns CS+/CS- change, performance index and weights."""
        trials = self.settings.trials if trials is None else trials
        exp = self._experiment(overrides, lesion_groups, seed)
        u = fruit_fly.US.Shock if us == "shock" else fruit_fly.US.Reward

        def step(phase, odour, with_us=False):
            s = fruit_fly.ProtocolStep()
            s.phase, s.odour = phase, odour
            if with_us:
                s.us = u
                if backward:                         # US ends 200 ms before the odour
                    s.us_onset_ms, s.us_ms = -(self.settings.stim_ms + 200.0), self.settings.stim_ms
            return s

        steps = [step("pre", "A"), step("pre", "B")]
        for _ in range(trials):
            steps += [step("training", "A", True), step("training", "B")]
        steps += [step("post", "A"), step("post", "B")]
        w0 = exp.simulator.plastic_weights()
        made = fruit_fly.run_protocol(exp, steps, {"A": self.stim.rates(plus), "B": self.stim.rates(minus)})
        r = fruit_fly.conditioning_readout(made, "A", "B", "pre", "post", u, trials, w0,
                                       exp.simulator.plastic_weights(), exp.spontaneous_hz)
        target = fruit_fly.dopamine_targets(self.net, exp.us_neurons(u))
        cc = fruit_fly.compartment_change(self.net, r, target)
        b = fruit_fly.tmaze_test(self.net, r)
        # Compartment specificity: the SAME Kenyon cells (those the CS+ activated)
        # in compartments that got the US dopamine vs compartments that didn't.
        # Averaging over all KCs would dilute the change ~15-fold, since only
        # ~7% of KCs respond to an odour.
        ratio = r.weights_after / self.net.plastic_w0
        cs_kcs = np.asarray(r.pre_plus.counts)[self.net.plastic_pre] > 0
        on_target = target[self.net.plastic_post]
        mbon = self._onto_mbon()                 # compartments = MBON synapses (not APL's)
        inside, outside = cs_kcs & on_target & mbon, cs_kcs & ~on_target & mbon
        return {
            "cs_plus": cc.cs_plus if cc.valid else math.nan,
            "cs_minus": cc.cs_minus if cc.valid else math.nan,
            "pi": b.performance_index if b.valid else math.nan,
            "target_ratio": float(ratio[inside].mean()) if inside.any() else math.nan,
            "other_ratio": float(ratio[outside].mean()) if outside.any() else math.nan,
        }


# ====================================================================== helpers

def kc_active(model: Model, resp: dict[str, np.ndarray]) -> list[float]:
    kcs = model.net.indices_in_group("KC")
    return [fruit_fly.fraction_active(c, kcs) for c in resp.values()]


def spearman(x: list[float], y: list[float]) -> float:
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1]) if len(x) > 2 else math.nan


def spread_pairs(model: Model, odours: list[str], k: int) -> list[tuple[str, str, float]]:
    """k odour pairs spanning the range of receptor-level similarity, chosen by
    rule (quantiles), not by hand, so the check can't be tuned by pair choice."""
    pairs = []
    for a, b in combinations(odours, 2):
        s = model.lib.similarity(a, b)
        if math.isfinite(s):
            pairs.append((a, b, s))
    pairs.sort(key=lambda p: p[2])
    if len(pairs) <= k:
        return pairs
    idx = sorted({round(q * (len(pairs) - 1)) for q in np.linspace(0, 1, k)})
    return [pairs[i] for i in idx]


def fmt_ratio(x: float) -> str:
    return f"{x:.2f}" if math.isfinite(x) else "n/a (control learned too little)"


def fmt(x: float, pct: bool = False) -> str:
    if x is None or not math.isfinite(x):
        return "n/a"
    return f"{x:+.0%}" if pct else f"{x:+.2f}"


# ====================================================================== calibration

def bisect(f, lo: float, hi: float, target: float, iters: int, log: bool = False,
           increasing: bool = True) -> float:
    """x in [lo, hi] where f crosses target. Raises ValueError if f is undefined (NaN)
    anywhere it is evaluated: a NaN compares as "below", which would otherwise walk
    the search silently to one end of the range."""
    for _ in range(iters):
        mid = math.sqrt(lo * hi) if log else (lo + hi) / 2
        value = f(mid)
        if not math.isfinite(value):
            raise ValueError(f"undefined at {mid:.3g}")
        above = value > target
        if above == increasing:
            hi = mid
        else:
            lo = mid
    return math.sqrt(lo * hi) if log else (lo + hi) / 2


def calibrate(model: Model, log=print, mbon_hz: float | None = None, per_type: bool = False,
              apl_half_range: bool = False) -> dict:
    out = {}
    odours = model.odours()[: max(6, model.settings.n_odours // 2)]

    def median_active(gain: float) -> float:
        return float(np.median(kc_active(model, model.responses(odours, {"graded_gain": gain}))))

    def median_rate(tonic: float) -> float:
        exp = model._experiment({"mbon_tonic_mV": tonic, "plasticity_on": False})
        exp.simulator.reset_counts()
        exp.simulator.run(2000.0)
        counts = np.asarray(exp.simulator.spike_counts())[model.net.indices_in_group("MBON")]
        return float(np.median(counts)) / 2.0

    apl = np.asarray(model.net.indices_in_group("APL"))
    v_max = fruit_fly.Params().graded_v_max_mV

    def apl_depol(gin: float) -> float:
        """Median over odours of APL's depolarisation during the odour."""
        exp = model._experiment({"graded_input_gain": gin, "plasticity_on": False})
        sim, out = exp.simulator, []
        for o in odours:
            sim.clear_rates(); sim.apply(exp.baseline); sim.apply(model.stim.rates(o))
            vs = []
            for _ in range(10):
                sim.run(50.0)
                vs.append(np.asarray(sim.voltages())[apl].mean() - model._params(None).v_rest_mV)
            out.append(np.mean(vs[2:]))
            sim.clear_rates(); sim.apply(exp.baseline); sim.run(1000.0)
        return float(np.median(out))

    # APL gain and MBON tonic input affect each other (APL inhibits MBONs; MBONs feed
    # back onto KCs), so calibrate them in turn, twice, each with the other's value.
    # With apl_half_range, APL's input gain is calibrated too, so a typical odour drives
    # APL to half its range instead of its ceiling.
    for _ in range(2 if (mbon_hz is not None or apl_half_range) else 1):
        if apl_half_range and len(apl):
            gin = bisect(apl_depol, 1e-4, 1.0, v_max / 2, iters=12, log=True)
            model.params["graded_input_gain"] = gin
            out["graded_input_gain"] = gin
        gain = bisect(median_active, 0.0, 0.5, KC_ACTIVE_TARGET, iters=7, increasing=False)
        model.params["graded_gain"] = gain
        if mbon_hz is not None:
            # MBONs fire spontaneously in flies; set the tonic input so the median MBON,
            # with no odour, fires at the measured rate (MBON-alpha3: 12.1 Hz, Hafez et al. 2023)
            tonic = bisect(median_rate, 0.0, 20.0, mbon_hz, iters=12)
            model.params["mbon_tonic_mV"] = tonic
            out["mbon_tonic_mV"] = tonic
    if apl_half_range and len(apl):
        log(f"  graded_input_gain = {gin:.4g}  (median odour drives APL to {apl_depol(gin):.1f} mV of {v_max:.0f})")
    log(f"  graded_gain   = {gain:.4f}  (median KCs active {median_active(gain):.1%})")
    if mbon_hz is not None:
        log(f"  mbon_tonic_mV = {tonic:.3f}  (median MBON {median_rate(tonic):.1f} Hz at rest; target {mbon_hz} Hz)")
    if mbon_hz is not None and per_type:
        # One input for all leaves strongly inhibited types silent (e.g. MBON01, needed for
        # the extinction circuit). MBON types inhibit each other, so independent bisections
        # don't converge; instead nudge every type's input by its rate error each round
        # (damped: 0.05 mV per Hz, at most 0.5 mV, shrinking in the last rounds).
        mbons = np.asarray(model.net.indices_in_group("MBON"))
        types = np.asarray(model.net.cell_type)[mbons]
        by_type = {t: model.params.get("mbon_tonic_mV", 0.0) for t in sorted(set(types))}
        rounds = 50
        for r in range(rounds):
            exp = model._experiment({"mbon_tonic_by_type": by_type, "plasticity_on": False})
            rate = np.asarray(exp.spontaneous_hz)[mbons]
            cap = 0.5 if r < rounds - 10 else 0.1
            for t in by_type:
                step = np.clip(0.05 * (rate[types == t].mean() - mbon_hz), -cap, cap)
                by_type[t] = float(np.clip(by_type[t] - step, 0.0, 40.0))
        by_type = {t: round(v, 4) for t, v in by_type.items()}
        model.params["mbon_tonic_by_type"] = by_type
        out["mbon_tonic_by_type"] = by_type
        exp = model._experiment({"plasticity_on": False})
        rate = np.asarray(exp.spontaneous_hz)[mbons]
        per = [rate[types == t].mean() for t in by_type]
        log(f"  mbon_tonic_by_type: {len(by_type)} types, {min(by_type.values()):.2f}-{max(by_type.values()):.2f} mV "
            f"(type rates {min(per):.1f}-{max(per):.1f} Hz, median {np.median(per):.1f}; target {mbon_hz} Hz)")

    # learning is calibrated on the most dissimilar pair of odours that measurably
    # excite the US compartments (with the gain and tonic input just set)
    measurable = model.measurable_odours(model.odours())
    pairs = spread_pairs(model, measurable, model.settings.n_pairs)
    if not pairs:
        problem = (f"learning_rate not calibrated: fewer than two test odours excite the US "
                   f"compartments ({len(measurable)} of {len(model.odours())})")
        log(f"  {problem}")
        return {**out, "graded_gain": gain, "learning_rate": None, "problems": [problem]}
    plus, minus, _ = pairs[0]

    def cs_plus(lr: float) -> float:
        return model.condition(plus, minus, overrides={"learning_rate": lr})["cs_plus"]

    # more learning -> more negative change: decreasing in lr
    try:
        lr = bisect(cs_plus, 1e-7, 1e-4, CS_PLUS_CHANGE_TARGET, iters=8, log=True, increasing=False)
    except ValueError:
        # No output neuron in the US compartments responds to the CS+, so learning
        # there can't be measured. Say so; don't report a meaningless value.
        problem = (f"learning_rate not calibrated: the CS+ response in the shock compartments is "
                   f"undefined ({plus} vs {minus}: none of their output neurons fired), so it was "
                   f"kept at {model.params.get('learning_rate', fruit_fly.Params().learning_rate):.3g}")
        log(f"  {problem}")
        return {**out, "graded_gain": gain, "learning_rate": None, "problems": [problem]}
    model.params["learning_rate"] = lr
    log(f"  learning_rate = {lr:.3g}  (CS+ change {fmt(cs_plus(lr), True)} on {plus} vs {minus})")
    return {**out, "graded_gain": gain, "learning_rate": lr, "problems": []}


# ====================================================================== checks

# Rescorla-Wagner: the expectation sums the predictions of every cue present, and
# shock and reward are opposite values of one prediction (an omitted US drives the
# opposite dopamine neurons by the net expectation).
RW = {"pe_expectation": "sum", "pe_omission": "net"}

def run_checks(model: Model, log=print) -> list[Check]:
    s = model.settings
    odours = model.odours()
    checks: list[Check] = []

    def add(c: Check) -> None:
        checks.append(c)
        verdict = {True: "pass", False: "FAIL", None: "info"}[c.passed]
        log(f"  [{verdict:4s}] {c.name}: {c.measured}")

    # ---- odour coding
    resp = model.responses(odours)
    active = kc_active(model, resp)
    med = float(np.median(active))
    add(Check("Sparse Kenyon cell code",
              "Each odour activates about 5-10% of Kenyon cells.",
              "Turner et al. 2008; Honegger et al. 2011",
              f"median {med:.1%} (range {min(active):.1%}-{max(active):.1%}, {len(odours)} odours)",
              "median 2-20%", 0.02 <= med <= 0.20))

    no_apl = kc_active(model, model.responses(odours, {"graded_gain": 0.0}))
    ratio = float(np.median(no_apl)) / med if med > 0 else math.inf
    add(Check("APL keeps the code sparse",
              "Blocking APL makes Kenyon cell responses larger and less odour-specific.",
              "Lin et al. 2014",
              f"median active {np.median(no_apl):.1%} without APL vs {med:.1%} ({ratio:.1f}x)",
              ">= 1.5x more active", ratio >= 1.5))

    pns, kcs = model.net.indices_in_group("ALPN"), model.net.indices_in_group("KC")
    decorrelated, total = 0, 0
    for a, b in combinations(odours, 2):
        pc, kc = fruit_fly.correlation(resp[a], resp[b], pns), fruit_fly.correlation(resp[a], resp[b], kcs)
        if math.isfinite(pc) and math.isfinite(kc):
            total += 1
            decorrelated += kc < pc
    frac = decorrelated / total if total else math.nan
    add(Check("Pattern separation",
              "Odour representations are less correlated in Kenyon cells than in projection neurons.",
              "Campbell et al. 2013",
              f"{decorrelated} of {total} odour pairs less correlated in KCs ({frac:.0%})",
              ">= 70% of pairs", total > 0 and frac >= 0.7))

    # ---- learning: only odours that measurably excite the US compartments
    measurable = model.measurable_odours(odours)
    add(Check("Odours that excite the US compartments",
              "Learning can only be read out for odours that drive the output neurons it changes.",
              "(selection rule)",
              f"{len(measurable)} of {len(odours)} test odours; not: "
              + (", ".join(o for o in odours if o not in measurable) or "none"),
              "reported; learning checks use these", None))
    pairs = spread_pairs(model, measurable, s.n_pairs)
    runs = [(a, b, sim, model.condition(a, b)) for a, b, sim in pairs]
    sims = [sim for *_, sim, _ in runs]
    minus_changes = [r["cs_minus"] for *_, r in runs]
    rho = spearman(sims, minus_changes)
    add(Check("Generalisation grows with odour similarity",
              "Flies generalise more between similar odours; the untrained odour is avoided more.",
              "Campbell et al. 2013; Barth et al. 2014",
              f"Spearman rho(similarity, CS- change) = {fmt(rho)} over {len(runs)} pairs "
              f"(similarity {min(sims):+.2f} to {max(sims):+.2f})",
              "rho < 0", math.isfinite(rho) and rho < 0,
              note="; ".join(f"{a} / {b}: r={sim:+.2f}, CS- {fmt(r['cs_minus'], True)}"
                             for a, b, sim, r in runs)))

    plus, minus, _, base = runs[0]                            # most dissimilar pair
    add(Check("Odour-specific memory",
              "Training changes the response to the trained odour, not to a dissimilar one.",
              "Tully & Quinn 1985; Hige et al. 2015",
              f"CS+ {fmt(base['cs_plus'], True)}, CS- {fmt(base['cs_minus'], True)} ({plus} / {minus})",
              "CS+ <= -30%, |CS-| < 15%",
              base["cs_plus"] <= -0.3 and abs(base["cs_minus"]) < 0.15))

    add(Check("Plasticity is compartment-specific",
              "Dopamine changes KC-MBON synapses only in the compartments it innervates.",
              "Hige et al. 2015; Aso & Rubin 2016",
              f"synapses of CS+ Kenyon cells: {base['target_ratio']:.0%} of initial in shock "
              f"compartments, {base['other_ratio']:.0%} elsewhere",
              "< 90% in, > 97% elsewhere",
              base["target_ratio"] < 0.9 and base["other_ratio"] > 0.97))

    curve = [(n, model.condition(plus, minus, trials=n)["pi"]) for n in s.acquisition]
    pis = [pi for _, pi in curve]
    rising = all(b >= a - 0.05 for a, b in zip(pis, pis[1:]))
    add(Check("Acquisition curve",
              "Memory grows with the number of pairings and saturates.",
              "Tully & Quinn 1985",
              ", ".join(f"{n} trials: {fmt(pi)}" for n, pi in curve),
              "PI(0) < 0.15, non-decreasing, PI(max) > PI(1)",
              pis[0] < 0.15 and rising and pis[-1] > pis[1]))

    reward = model.condition(plus, minus, us="reward")
    add(Check("Shock teaches avoidance, reward approach",
              "Flies avoid odours paired with shock and approach odours paired with sugar.",
              "Tully & Quinn 1985; Tempel et al. 1983",
              f"PI shock {fmt(base['pi'])}, reward {fmt(reward['pi'])} (positive = as taught)",
              "both > 0.3", base["pi"] > 0.3 and reward["pi"] > 0.3))

    no_ppl1 = model.condition(plus, minus, lesion_groups=("DAN_PPL1",))
    add(Check("PPL1 dopamine neurons are needed for shock learning",
              "Blocking these dopamine neurons abolishes aversive memory.",
              "Schwaerzel et al. 2003; Aso et al. 2010",
              f"PI {fmt(no_ppl1['pi'])} with PPL1 silenced vs {fmt(base['pi'])} intact",
              "|PI| < 0.1", abs(no_ppl1["pi"]) < 0.1))

    no_pam = model.condition(plus, minus, us="reward", lesion_groups=("DAN_PAM",))
    add(Check("PAM dopamine neurons are needed for reward learning",
              "Blocking PAM neurons abolishes appetitive memory.",
              "Liu et al. 2012; Burke et al. 2012",
              f"PI {fmt(no_pam['pi'])} with PAM silenced vs {fmt(reward['pi'])} intact",
              "|PI| < 0.1", abs(no_pam["pi"]) < 0.1))

    timing = {"plasticity_rule": "timing"}
    fwd = model.condition(plus, minus, overrides=timing)
    bwd = model.condition(plus, minus, overrides=timing, backward=True)
    add(Check("Backward pairing gives relief learning",
              "An odour that follows a shock becomes attractive, much more weakly than "
              "forward pairing makes it aversive.",
              "Tanimoto et al. 2004; Handler et al. 2019",
              f"PI backward {fmt(bwd['pi'])}, forward {fmt(fwd['pi'])} (timing rule)",
              "backward < 0, |backward| < forward",
              bwd["pi"] < 0 and abs(bwd["pi"]) < fwd["pi"]))

    trained, extinguished = model.extinction(plus, minus, overrides={"prediction_error": True, **RW})
    plain_trained, plain_ext = model.extinction(plus, minus)
    add(Check("Extinction (prediction-error dopamine)",
              "Presenting the trained odour without shock weakens avoidance, through an opposing "
              "memory formed by reward dopamine neurons; it is reduced, not erased.",
              "Schwaerzel et al. 2002; Felsenberg et al. 2018",
              f"PI {fmt(trained)} after training -> {fmt(extinguished)} after 6 unpaired CS+ "
              f"(without prediction error: {fmt(plain_trained)} -> {fmt(plain_ext)})",
              "reduced by >= 40%, still >= -0.2",
              trained > 0.3 and extinguished <= 0.6 * trained and extinguished >= -0.2))

    # Blocking: X is the odour least similar to A (distinct KCs) among those of comparable
    # salience, i.e. evoking at least half of A's response in the shock compartments;
    # blocking designs match cue salience, and in Rescorla-Wagner salience sets the rate.
    salient = [o for o in measurable if o not in (plus, minus)
               and model.evoked_shock.get(o, 0.0) >= 0.5 * model.evoked_shock.get(plus, 0.0)]
    x = min(salient or [o for o in measurable if o not in (plus, minus)],
            key=lambda o: model.lib.similarity(plus, o))
    blk = model.blocking(plus, minus, x, overrides={"pe_us": True, **RW})
    plain = model.blocking(plus, minus, x)
    # compounds with odours competing for each receptor (Münch et al. 2013), not adding
    bound = model.blocking(plus, minus, x, overrides={"pe_us": True, **RW, "mixture": "binding"})
    # a ratio needs a control that learned: below this, report n/a, not a meaningless number
    floor = {"pi": 0.1, "synapses_lost": 0.05}
    ratio = lambda r, k: (r["blocked"][k] / r["control"][k]
                          if abs(r["control"][k]) >= floor[k] else math.nan)
    add(Check("Blocking (Rescorla-Wagner US prediction)",
              "A cue trained together with one that already predicts the US learns less "
              "(Kamin blocking). Prediction-error learning rules predict it; whether flies show it "
              "in odour learning is not judged here.",
              "Kamin 1969; Rescorla & Wagner 1972",
              f"X after pretrained A vs control: PI {fmt(blk['blocked']['pi'])} vs {fmt(blk['control']['pi'])} "
              f"(ratio {fmt_ratio(ratio(blk, 'pi'))}); X-only synapses lost {fmt(blk['blocked']['synapses_lost'], True)} "
              f"vs {fmt(blk['control']['synapses_lost'], True)} (ratio {fmt_ratio(ratio(blk, 'synapses_lost'))}); "
              f"without US prediction: PI ratio {fmt_ratio(ratio(plain, 'pi'))}, synapse ratio "
              f"{fmt_ratio(ratio(plain, 'synapses_lost'))}; with receptor competition in the compound: "
              f"PI ratio {fmt_ratio(ratio(bound, 'pi'))}, synapse ratio {fmt_ratio(ratio(bound, 'synapses_lost'))} "
              f"({plus}, {x}; {minus} as CS-)",
              "reported, not judged", None,
              note="Ratio 1 = no blocking, 0 = complete. The synapse ratio is the learning itself; "
                   "the performance index passes through the output neurons' spike threshold, which "
                   "turns a small weight loss into a large drop in output and so compresses blocking."))
    return checks


# ====================================================================== report

def report(checks: list[Check], model: Model, circuit: Path, calibration: dict | None,
           seconds: float) -> str:
    judged = [c for c in checks if c.passed is not None]
    passed = sum(c.passed for c in judged)
    synthetic = "synthetic" in str(circuit)
    lines = [
        "# Model validation",
        "",
        f"- Circuit: `{circuit}` ({len(model.net)} neurons)"
        + (" - **synthetic test circuit: these numbers say nothing about the real fly**" if synthetic else ""),
        f"- Run: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, {seconds:.0f} s, seed {model.settings.seed}",
        f"- Parameters: " + (", ".join(f"`{k}` = {v:.4g}" if isinstance(v, float) else
                        f"`{k}` = {len(v)} values" if isinstance(v, dict) else f"`{k}` = {v}"
                                        for k, v in model.params.items())
                             if model.params else "defaults")
        + ((" (calibrated: " + ", ".join(k for k in ("graded_input_gain", "mbon_tonic_mV", "mbon_tonic_by_type", "graded_gain", "learning_rate")
                                           if calibration.get(k) is not None) + ")") if calibration else ""),
        *[f"- **Calibration problem:** {p}" for p in (calibration or {}).get("problems", [])],
        f"- **{passed} of {len(judged)} checks passed**",
        "",
        "| Check | In flies | Model | Target | Result |",
        "|---|---|---|---|---|",
    ]
    for c in checks:
        verdict = {True: "pass", False: "**FAIL**", None: "info"}[c.passed]
        lines.append(f"| {c.name} | {c.finding} ({c.reference}) | {c.measured} | {c.target} | {verdict} |")
    notes = [c for c in checks if c.note]
    if notes:
        lines += ["", "## Details", ""]
        lines += [f"- **{c.name}:** {c.note}" for c in notes]
    lines += ["", "## How to read this", "",
              "A pass means the model reproduces the qualitative finding at the stated threshold, "
              "with parameters calibrated only on Kenyon cell sparseness and learning strength, "
              "never on the findings being checked. A known gap (second-order conditioning) is "
              "described in `docs/CIRCUIT.md`.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--circuit", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--door", type=Path, default=Path("data/raw/door"))
    ap.add_argument("--params", type=Path, help="JSON parameter overrides to start from")
    ap.add_argument("--calibrate", action="store_true", help="calibrate graded_gain and learning_rate first")
    ap.add_argument("--params-out", type=Path, help="write the calibrated parameters here (JSON)")
    ap.add_argument("--apl-half-range", action=argparse.BooleanOptionalAction, default=True,
                    help="calibrate APL's input gain so a typical odour drives it to half its range "
                         "(default; --no-apl-half-range keeps the standard per-synapse weight)")
    ap.add_argument("--mbon-tonic", choices=["uniform", "per-type"], default="uniform",
                    help="calibrate the MBON input per cell type, or one value for all")
    ap.add_argument("--mbon-spontaneous-hz", type=float, default=12.1,
                    help="calibrate MBON tonic input to this spontaneous rate (MBON-alpha3, Hafez et al. 2023); 0 = silent MBONs")
    ap.add_argument("--out", type=Path, help="write the Markdown report here")
    ap.add_argument("--quick", action="store_true", help="fewer odours and shorter presentations")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    settings = Settings.quick() if args.quick else Settings()
    settings.seed = args.seed
    params = json.loads(args.params.read_text()) if args.params else {}
    t0 = time.time()
    model = Model.load(args.circuit, args.door, settings, params)
    print(f"circuit {args.circuit}: {len(model.net)} neurons; {len(model.odours())} test odours")

    calibration = None
    if args.calibrate:
        print("calibrating")
        calibration = calibrate(model, mbon_hz=args.mbon_spontaneous_hz or None,
                                per_type=args.mbon_tonic == "per-type", apl_half_range=args.apl_half_range)
        if args.params_out:
            args.params_out.parent.mkdir(parents=True, exist_ok=True)
            args.params_out.write_text(json.dumps(model.params, indent=2) + "\n")
            print(f"  wrote {args.params_out}")
    print("checks")
    checks = run_checks(model)
    text = report(checks, model, args.circuit, calibration, time.time() - t0)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    judged = [c for c in checks if c.passed is not None]
    print(f"{sum(c.passed for c in judged)} of {len(judged)} checks passed")
    return 0 if all(c.passed for c in judged) else 1


if __name__ == "__main__":
    sys.exit(main())