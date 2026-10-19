"""Ready-made protocols for classic conditioning paradigms.

Each preset is a complete set of request fields (steps, readout, parameter
overrides, extra odour slots). The frontend offers them in a menu; clients can
also copy one and edit the steps.
"""

from __future__ import annotations

from pydantic import BaseModel

from .schemas import ProtocolStepModel as S
from .schemas import Readout, default_steps


class Preset(BaseModel):
    name: str
    title: str
    description: str            # what the protocol does
    in_flies: str               # what flies do, with references
    in_model: str               # what to expect from this model, including its limits
    steps: list[S]
    readout: Readout
    params: dict[str, bool | float | str] = {}
    extra_odour_slots: list[str] = []


def _train(n: int, plus: str, minus: str, phase: str, **us) -> list[S]:
    out: list[S] = []
    for _ in range(n):
        out += [S(phase=phase, odour=plus, us="shock", **us), S(phase=phase, odour=minus)]
    return out


def _test(phase: str, *slots: str) -> list[S]:
    return [S(phase=phase, odour=s) for s in slots]



_BLOCKING_IN_FLIES = ("Kamin blocking (Kamin 1969) is the classic test of prediction-error learning: "
                      "a cue that already predicts the US blocks learning about a new cue trained "
                      "with it (Rescorla & Wagner 1972). Whether flies show it in odour learning "
                      "is not settled by this model; check the primary literature.")


def _blocking_steps(pretrain_us: str) -> list[S]:
    return [*_test("pre", "C", "B"),
            *[s for _ in range(10) for s in (S(phase="pretraining", odour="A", us=pretrain_us),
                                             S(phase="pretraining", odour="B"))],
            *_train(3, "A+C", "B", "compound"),
            *_test("post", "C", "B")]


PRESETS: list[Preset] = [
    Preset(
        name="differential",
        title="Differential conditioning",
        description="Test A and B; pair A with shock and present B alone, 3 times; test again.",
        in_flies="Flies avoid A afterwards (Tully & Quinn 1985). The standard paradigm.",
        in_model="Strong, odour-specific avoidance of A (performance index around +0.6 on the "
                 "synthetic circuit); similar odours generalise more.",
        steps=default_steps(3, "shock"),
        readout=Readout(),
    ),
    Preset(
        name="extinction",
        title="Extinction",
        description="Train as above, test, then present A alone 6 times, and test again.",
        in_flies="Repeated unreinforced A weakens the avoidance (Schwaerzel et al. 2002). It works "
                 "partly by forming a new, opposing reward memory, driven by dopamine neurons "
                 "that signal the omitted shock (Felsenberg et al. 2018).",
        in_model="With prediction-error dopamine (on in this preset, with the Rescorla-Wagner "
                 "expectation): the trained odour, presented without the expected shock, drives the "
                 "reward (PAM) dopamine neurons, which weaken its synapses onto avoidance-promoting "
                 "output neurons. Avoidance falls but isn't erased (about a third on the synthetic "
                 "circuit). Turn prediction_error off to see the original model, which has no signal "
                 "for an omitted shock and so does not extinguish at all.",
        steps=[*_test("pre", "A", "B"), *_train(3, "A", "B", "training"),
               *_test("after training", "A", "B"),
               S(phase="extinction", odour="A", repeat=6),
               *_test("after extinction", "A", "B")],
        readout=Readout(before="pre", after="after extinction"),
        params={"prediction_error": True, "pe_expectation": "sum"},
    ),
    Preset(
        name="reversal",
        title="Reversal learning",
        description="Train A+ / B-, test, then swap: B+ / A-, and test. The readout compares B "
                    "with A across the reversal.",
        in_flies="Flies learn the reversed contingency and come to avoid B (Wu et al. 2012).",
        in_model="B's memory forms as in normal training. A's weakened synapses don't recover "
                 "(there is no rule that restores them without dopamine), so A stays somewhat "
                 "avoided; the readout shows how much the preference shifts towards avoiding B.",
        steps=[*_test("pre", "A", "B"), *_train(3, "A", "B", "first training"),
               *_test("after first training", "A", "B"),
               *_train(3, "B", "A", "reversal"), *_test("post", "A", "B")],
        readout=Readout(plus="B", minus="A", before="after first training", after="post"),
    ),
    Preset(
        name="second_order",
        title="Second-order conditioning",
        description="Train A with shock; then present a new odour C immediately before A (no "
                    "shock), 3 times; test C against B.",
        in_flies="C becomes aversive through its association with A (Tabone & de Belle 2011). "
                 "It needs a pathway from the first memory to dopamine neurons: a feedforward "
                 "circuit between dopamine subsystems (Yamada et al. 2023).",
        in_model="Depends on MBON-to-DAN feedback in the circuit: A must make DANs fire when "
                 "presented alone. With little such feedback (as in the synthetic circuit), expect "
                 "a weak or absent effect; on the real FlyWire circuit this is a genuine test.",
        steps=[*_test("pre", "A", "B", "C"),
               S(phase="first order", odour="A", us="shock", repeat=3),
               *[s for _ in range(3) for s in (S(phase="second order", odour="C", gap_ms=0.0),
                                                S(phase="second order", odour="A"))],
               *_test("post", "C", "B")],
        readout=Readout(plus="C", minus="B"),
        extra_odour_slots=["C"],
    ),
    Preset(
        name="backward_pairing",
        title="Backward pairing (relief learning)",
        description="The shock ends 200 ms before odour A starts. Uses the timing-dependent "
                    "learning rule.",
        in_flies="The odour that follows a shock becomes mildly attractive: 'relief' learning "
                 "(Tanimoto et al. 2004), much weaker than punishment learning, and single dopamine "
                 "neurons can reinforce both depending on timing (König et al. 2018). At the synapse, "
                 "dopamine before KC activity strengthens it (Handler et al. 2019).",
        in_model="A negative performance index (A approached), weaker than forward pairing: "
                 "about -0.2 to -0.3 on the synthetic circuit (varies with the seed), vs about +0.6 forward. Compare with "
                 "the 'forward pairing (timing rule)' preset.",
        steps=[*_test("pre", "A", "B"),
               *_train(3, "A", "B", "training", us_onset_ms=-1200.0, us_ms=1000.0),
               *_test("post", "A", "B")],
        readout=Readout(),
        params={"plasticity_rule": "timing"},
    ),
    Preset(
        name="forward_timing",
        title="Forward pairing (timing rule)",
        description="Differential conditioning with the timing-dependent learning rule: the "
                    "control for backward pairing.",
        in_flies="Shock during the odour produces avoidance.",
        in_model="Strong avoidance, as with the default rule; the comparison isolates the effect "
                 "of the shock's timing.",
        steps=default_steps(3, "shock"),
        readout=Readout(),
        params={"plasticity_rule": "timing"},
    ),
    Preset(
        name="blocking",
        title="Blocking (Kamin)",
        description="Pretrain A with shock (10 times), then train the compound A+C with shock "
                    "(3 times); B is the unpaired CS-. The readout tests C alone against B.",
        in_flies=_BLOCKING_IN_FLIES,
        in_model="With the Rescorla-Wagner US prediction (on in this preset), A predicts the shock, "
                 "so the shock during A+C releases less dopamine and C learns less than in the "
                 "control preset: about half as much at the synapses on the synthetic circuit, less "
                 "visibly in the performance index, which the output neurons' spike threshold "
                 "compresses. Compare with 'Blocking control'.",
        steps=_blocking_steps("shock"),
        readout=Readout(plus="C", minus="B", before="pre", after="post"),
        params={"pe_us": True, "pe_expectation": "sum"},
        extra_odour_slots=["C"],
    ),
    Preset(
        name="blocking_control",
        title="Blocking control",
        description="As 'Blocking', but A is presented without shock during pretraining, so it "
                    "predicts nothing when A+C is trained.",
        in_flies=_BLOCKING_IN_FLIES,
        in_model="C learns at the full rate: the reference for the blocking preset.",
        steps=_blocking_steps("none"),
        readout=Readout(plus="C", minus="B", before="pre", after="post"),
        params={"pe_us": True, "pe_expectation": "sum"},
        extra_odour_slots=["C"],
    ),
]

PRESETS_BY_NAME = {p.name: p for p in PRESETS}