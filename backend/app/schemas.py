"""Request and response shapes. FastAPI validates every request against these
and uses them to generate the OpenAPI docs at /docs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ============================================================ requests

class ParamOverrides(BaseModel):
    """Model parameters that may change per experiment. Only parameters that
    take effect at simulation time are allowed; the ones baked into the
    loaded circuit (synapse weights, graded groups) are not. Unknown names are
    an error: a typo must not silently fall back to the default."""

    model_config = ConfigDict(extra="forbid")

    graded_gain: float | None = Field(
        None, ge=0.0, le=1.0, description="APL inhibition strength (default 0.05; 0 = APL off)")
    learning_rate: float | None = Field(None, ge=0.0, le=1e-3, description="default 2e-6")
    plasticity_on: bool | None = None
    tau_elig_ms: float | None = Field(None, gt=0.0, le=10_000.0)
    tau_da_ms: float | None = Field(None, gt=0.0, le=10_000.0)
    plasticity_rule: Literal["overlap", "timing"] | None = Field(
        None, description="'timing': order of KC and dopamine activity sets the sign (needed for "
                          "backward pairing); default 'overlap'")
    timing_depression: float | None = Field(None, ge=0.0, le=0.1)
    timing_potentiation: float | None = Field(None, ge=0.0, le=0.1)
    prediction_error: bool | None = Field(
        None, description="dopamine neurons also signal omitted expected USs (enables extinction)")
    pe_gain_hz: float | None = Field(None, ge=0.0, le=200.0, description="default 20")
    pe_us: bool | None = Field(
        None, description="an expected US releases less dopamine (Rescorla-Wagner; enables blocking)")
    pe_expectation: Literal["average", "sum"] | None = Field(
        None, description="'sum': Rescorla-Wagner, cues present add their predictions; default 'average'")
    pe_omission: Literal["separate", "net"] | None = Field(
        None, description="'net': an omitted US drives the opposite dopamine neurons by the net "
                          "(shock minus reward) expectation; default 'separate'")
    pe_ref_active_frac: float | None = Field(
        None, gt=0.0, le=1.0, description="'sum' asymptote: fraction of KCs one odour activates (0.07)")
    mbon_tonic_mV: float | None = Field(
        None, ge=0.0, le=20.0, description="constant depolarising input to MBONs (spontaneous firing); default 0")
    graded_input_gain: float | None = Field(
        None, gt=0.0, le=10.0, description="scale on input to graded neurons (APL); calibrated, default 1")
    apl_plasticity: bool | None = Field(
        None, description="dopamine suppresses KC -> APL input (Zhou et al. 2019); default off")
    mbon_tonic_by_type: dict[str, float] | None = Field(
        None, description="per MBON cell type, overriding mbon_tonic_mV (from calibration)")
    kc_dan_gain: float | None = Field(
        None, ge=0.0, le=100.0,
        description="with a circuit loaded as kc_dan='terminal': KC gain on dopamine release; default 0")
    mixture: Literal["linear", "binding"] | None = Field(
        None, description="compound odours: 'binding' = odours compete for each receptor's binding site "
                          "(Münch et al. 2013); 'linear' = changes add; default 'linear'")


class ServerParams(ParamOverrides):
    """FRUIT_FLY_PARAMS_FILE: experiment defaults, plus settings that shape the loaded
    circuit itself and so can't change per request."""
    kc_dan: Literal["fast", "terminal"] | None = Field(
        None, description="KC -> DAN synapses: 'fast' (as listed) or 'terminal' (gain on release)")


class ProtocolSettings(BaseModel):
    stim_ms: float = Field(1000.0, gt=0.0, le=10_000.0)
    gap_ms: float = Field(2000.0, ge=0.0, le=20_000.0)
    settle_ms: float = Field(500.0, ge=0.0, le=10_000.0)
    us_hz: float = Field(40.0, ge=0.0, le=200.0)


class BehaviorSettings(BaseModel):
    """T-maze readout: how MBON output is turned into choices."""
    sharpness: float = Field(6.0, gt=0.0, le=100.0,
                             description="how strongly drive differences decide the choice")
    flies: int = Field(100, ge=1, le=100_000, description="flies per simulated group")


Slot = Literal["A", "B", "C", "D"]          # A = cs_plus, B = cs_minus, C/D = extra_odours
# A step's odour: one slot, or a compound presented together, e.g. "A+C"
OdourKey = Annotated[str, Field(pattern=r"^[ABCD](\+[ABCD]){0,3}$")]


def compound_slots(key: str) -> list[str]:
    """ "A+C" -> ["A", "C"]."""
    return key.split("+")

MAX_PRESENTATIONS = 200
MAX_SIMULATED_S = 900


class ProtocolStepModel(BaseModel):
    """One protocol step: an odour and/or a US. us_onset_ms is relative to the
    odour onset; negative values put the US before the odour (backward pairing).
    Unset durations use the `protocol` defaults."""
    phase: str = Field(..., min_length=1, max_length=40)
    odour: OdourKey | None = None
    us: Literal["none", "shock", "reward"] = "none"
    odour_ms: float | None = Field(None, gt=0.0, le=10_000.0)
    us_onset_ms: float = Field(0.0, ge=-10_000.0, le=10_000.0)
    us_ms: float | None = Field(None, gt=0.0, le=10_000.0)
    gap_ms: float | None = Field(None, ge=0.0, le=20_000.0)
    repeat: int = Field(1, ge=1, le=50)

    @model_validator(mode="after")
    def odour_or_us(self) -> "ProtocolStepModel":
        if self.odour is None and self.us == "none":
            raise ValueError("a step needs an odour, a US, or both")
        if self.odour is not None and len(set(compound_slots(self.odour))) != len(compound_slots(self.odour)):
            raise ValueError(f"odour {self.odour} names a slot twice")
        return self


class Readout(BaseModel):
    """Which presentations the results compare: the first US-free presentation
    of `plus` and `minus` in phase `before`, and again in phase `after`."""
    plus: Slot = "A"
    minus: Slot = "B"
    before: str = Field("pre", min_length=1, max_length=40)
    after: str = Field("post", min_length=1, max_length=40)


class Lesion(BaseModel):
    """Silence every neuron of a group (e.g. "APL", "DAN_PPL1") or of a cell type (e.g. "MBON01")."""
    group: str | None = Field(None, min_length=1, max_length=64)
    cell_type: str | None = Field(None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def exactly_one(self) -> "Lesion":
        if (self.group is None) == (self.cell_type is None):
            raise ValueError("a lesion names exactly one of group or cell_type")
        return self


def default_steps(trials: int, us: str) -> list[ProtocolStepModel]:
    """The classic differential protocol: test A and B, train (A + US, B) x trials, test again."""
    S = ProtocolStepModel
    steps = [S(phase="pre", odour="A"), S(phase="pre", odour="B")]
    for _ in range(trials):
        steps += [S(phase="training", odour="A", us=us), S(phase="training", odour="B")]
    return steps + [S(phase="post", odour="A"), S(phase="post", odour="B")]


class ConditioningRequest(BaseModel):
    cs_plus: str = Field("3-octanol", min_length=1, max_length=200)
    cs_minus: str = Field("4-methylcyclohexanol", min_length=1, max_length=200)
    odour_source: Literal["door", "random"] = "door"
    trials: int = Field(3, ge=0, le=20)
    us: Literal["shock", "reward"] = "shock"
    seed: int = Field(1, ge=0, le=2**63 - 1)
    params: ParamOverrides = Field(default_factory=ParamOverrides)
    protocol: ProtocolSettings = Field(default_factory=ProtocolSettings)
    behavior: BehaviorSettings = Field(default_factory=BehaviorSettings)
    # Custom protocol; None = the classic differential protocol built from `trials`
    # (with steps given, `trials` is ignored).
    steps: list[ProtocolStepModel] | None = Field(None, min_length=1, max_length=40)
    extra_odours: dict[Literal["C", "D"], str] = Field(default_factory=dict)
    readout: Readout = Field(default_factory=Readout)
    lesions: list[Lesion] = Field(default_factory=list, max_length=20)

    def effective_steps(self) -> list[ProtocolStepModel]:
        return self.steps if self.steps is not None else default_steps(self.trials, self.us)

    @model_validator(mode="after")
    def consistent(self) -> "ConditioningRequest":
        if self.cs_plus.strip().lower() == self.cs_minus.strip().lower():
            raise ValueError("cs_plus and cs_minus must be different odours")
        for slot, name in self.extra_odours.items():
            if not name.strip():
                raise ValueError(f"extra_odours.{slot} is empty")
        steps = self.effective_steps()
        slots = {"A", "B", *self.extra_odours}
        presentations, simulated_ms = 0, 0.0
        for i, st in enumerate(steps):
            for slot in compound_slots(st.odour) if st.odour is not None else []:
                if slot not in slots:
                    raise ValueError(f"step {i + 1} uses odour {slot}, but extra_odours has no {slot}")
            if st.us not in ("none", self.us):
                raise ValueError(f"step {i + 1} uses US '{st.us}' but the experiment's us is "
                                 f"'{self.us}'; one protocol uses one kind of US")
            odour_ms = st.odour_ms or self.protocol.stim_ms
            us_ms = st.us_ms or (odour_ms if st.odour else self.protocol.stim_ms)
            start = min(0.0, st.us_onset_ms) if st.us != "none" else 0.0
            end = max(odour_ms if st.odour else 0.0, st.us_onset_ms + us_ms if st.us != "none" else 0.0)
            gap = self.protocol.gap_ms if st.gap_ms is None else st.gap_ms
            presentations += st.repeat
            simulated_ms += st.repeat * (end - start + gap)
        if presentations > MAX_PRESENTATIONS:
            raise ValueError(f"protocol has {presentations} presentations; the limit is {MAX_PRESENTATIONS}")
        if simulated_ms > MAX_SIMULATED_S * 1000:
            raise ValueError(f"protocol simulates {simulated_ms / 1000:.0f} s; the limit is {MAX_SIMULATED_S} s")
        ro = self.readout
        if ro.plus == ro.minus:
            raise ValueError("readout.plus and readout.minus must be different odours")
        for slot in (ro.plus, ro.minus):
            if slot not in slots:
                raise ValueError(f"readout uses odour {slot}, which isn't defined")
            for phase in (ro.before, ro.after):
                if not any(st.odour == slot and st.phase == phase and st.us == "none" for st in steps):
                    raise ValueError(f"readout needs a US-free presentation of {slot} in phase '{phase}'")
        return self


# ============================================================ circuit

class CircuitSummary(BaseModel):
    circuit_dir: str
    neurons: int
    fast_synapses: int
    plastic_synapses: int
    groups: dict[str, int]
    mbons_with_ppl1_dopamine: int
    mbons_with_pam_dopamine: int
    odours_loaded: bool
    default_params: dict[str, float | str | bool] = {}
    anatomy: "Anatomy"


class Anatomy(BaseModel):
    """Which drawing aids the circuit folder has (scripts/build_anatomy.py)."""
    regions: bool                   # GET /api/circuit/regions: brain region meshes
    morphology: bool                # GET /api/circuit/morphology: neuron shapes


class Bounds(BaseModel):
    min: list[float]
    max: list[float]


class NeuronTable(BaseModel):
    """Column-oriented: element i of every list describes neuron index i."""
    count: int
    root_id: list[str]
    flywire_id: list[str]           # the FlyWire neuron each unit belongs to (its shape in the morphology file)
    group: list[str]
    cell_type: list[str]
    x: list[float | None]
    y: list[float | None]
    z: list[float | None]
    bounds: Bounds | None
    groups: list[str]


# ============================================================ odours

class OdourListItem(BaseModel):
    name: str
    coverage: float


class OdourCatalogItem(BaseModel):
    name: str
    chemical_class: str             # DoOR's class, e.g. "esters"; "unclassified" if DoOR has none
    coverage: float                 # share of receptors DoOR measured for this odour


class OdourCatalog(BaseModel):
    items: list[OdourCatalogItem]   # alphabetical


class OdourList(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[OdourListItem]


class GlomerulusResponse(BaseModel):
    glomerulus: str
    response: float | None          # None = never measured
    spontaneous: float


class OdourDetail(BaseModel):
    name: str
    coverage: float
    glomeruli: list[GlomerulusResponse]


class OdourSimilarity(BaseModel):
    a: str
    b: str
    similarity: float | None        # None = too few glomeruli measured for both


# ============================================================ experiments

class ExperimentStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Separation(BaseModel):
    pn_correlation: float | None
    kc_correlation: float | None
    kc_active_plus: float
    kc_active_minus: float
    kc_shared: int


class MbonSummary(BaseModel):
    cell_type: str
    n: int
    us_target: bool
    pre_plus: float
    post_plus: float
    pre_minus: float
    post_minus: float


class CompartmentChange(BaseModel):
    valid: bool
    cs_plus: float | None
    cs_minus: float | None


class MbonWeight(BaseModel):
    index: int
    cell_type: str
    weight_ratio: float             # mean after / initial over its KC inputs


class Partner(BaseModel):
    """Connections to or from the neurons of one cell type."""
    cell_type: str
    group: str
    neurons: int                    # how many neurons of this type connect
    synapses: int
    sign: Literal["excitatory", "inhibitory", "modulatory"]


class Connection(BaseModel):
    index: int                      # the partner neuron
    synapses: int
    sign: Literal["excitatory", "inhibitory", "modulatory"]


class NeuronConnections(BaseModel):
    """Every partner neuron of one neuron (fast synapses, strongest first), and the
    dopamine coupling between DANs and MBONs, which acts through plasticity."""
    index: int
    min_synapses: int
    total_inputs: int               # partners with >= min_synapses, before `limit`
    total_outputs: int
    inputs: list[Connection]
    outputs: list[Connection]
    dopamine_to: list[int]          # a DAN: the MBONs its dopamine reaches
    dopamine_from: list[int]        # an MBON: the DANs whose dopamine reaches it


class GroupConnection(BaseModel):
    pre: str
    post: str
    synapses: int                   # 0 for dopamine coupling
    connections: int                # connected neuron pairs
    sign: Literal["excitatory", "inhibitory", "modulatory", "mixed", "dopamine"]


class NeuronDetail(BaseModel):
    """One neuron and its fast connections in the model (excluded connections, such as
    KC -> KC, and DAN dopamine, which acts through plasticity, are not listed)."""
    index: int
    root_id: str                    # the model's id
    flywire_id: str                 # FlyWire's id (differs for units standing for part of a neuron)
    region: str                     # that part's MB region, e.g. "ML" for a regional APL unit; "" if whole
    group: str
    cell_type: str
    side: str
    transmitter: str                # "" if unknown
    graded: bool                    # non-spiking (e.g. APL)
    input_synapses: int
    output_synapses: int
    inputs: list[Partner]           # largest first, at most `limit`
    outputs: list[Partner]


class PresentationActivity(BaseModel):
    label: str
    phase: str
    us: Literal["none", "shock", "reward"]
    t_start_ms: float
    t_end_ms: float
    spikes: int
    rate_hz: float


class NeuronActivity(BaseModel):
    """One neuron's spikes in each presentation of an experiment."""
    index: int
    total_spikes: int
    presentations: list[PresentationActivity]


class TimelineEntry(BaseModel):
    label: str                      # odour name, or "US" for a US-only step
    slot: str | None                # odour slot (A-D), None for a US-only step
    us: Literal["none", "shock", "reward"]
    phase: str
    t_start_ms: float               # counting window (odour, or the US for a US-only step)
    t_end_ms: float
    us_start_ms: float | None       # US window, None without a US
    us_end_ms: float | None


class TMazeChoice(BaseModel):
    drive_plus: float | None        # approach drive of CS+, -1 (avoid) .. +1 (approach)
    drive_minus: float | None
    p_plus: float                   # probability of entering the CS+ arm
    preference: float               # p(CS+) - p(CS-)


class Behavior(BaseModel):
    valid: bool                     # False: no prediction possible (see valenced_mbons)
    valenced_mbons: int             # MBONs with a known approach/avoid valence
    naive: TMazeChoice              # one group before training (includes innate bias)
    trained: TMazeChoice            # the same after training
    learned_drive: float | None     # None when not valid
    performance_index: float | None # (-1, 1); positive = learned as the US teaches
    flies: int
    sampled_performance_index: float | None


class ExperimentResult(BaseModel):
    separation: Separation
    mbons: list[MbonSummary]
    compartment_change: CompartmentChange
    mean_weight_ratio: float | None
    mbon_weights: list[MbonWeight]
    timeline: list[TimelineEntry]
    duration_ms: float
    n_spikes: int
    coverage: dict[str, float] | None       # DoOR coverage per odour, None for random odours
    input_similarity: float | None
    behavior: Behavior
    readout: Readout                # which presentations the numbers above compare
    readout_after_ms: float         # when the "after" readout presentations start
    odours: dict[str, str]           # slot -> odour name
    lesioned: list[int]             # silenced neuron indices


class Progress(BaseModel):
    done: int          # odour presentations finished
    total: int


class ExperimentSummary(BaseModel):
    id: str
    sweep_id: str | None            # set for experiments created by a sweep
    status: ExperimentStatus
    progress: Progress | None       # None until the simulation starts
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    request: ConditioningRequest
    error: str | None


class ExperimentDetail(ExperimentSummary):
    result: ExperimentResult | None


class ExperimentPage(BaseModel):
    """One page of a list, newest first. Pass `next_cursor` as `cursor` for the
    next page; None means this is the last one."""
    items: list[ExperimentSummary]
    next_cursor: str | None


class CancelResult(BaseModel):
    status: ExperimentStatus        # "cancelled", or "running" while the worker stops


class SpikeWindow(BaseModel):
    """Spikes with t0 <= t < t1, sorted by time. `neurons[i]` fired at `times_ms[i]`."""
    t0_ms: float
    t1_ms: float
    count: int
    truncated: bool                 # True if max_spikes cut the window short
    neurons: list[int]
    times_ms: list[float]


# ============================================================ sweeps

SweepParameter = Literal[
    "params.graded_gain", "params.learning_rate", "params.tau_elig_ms", "params.tau_da_ms",
    "protocol.us_hz", "protocol.stim_ms", "trials", "behavior.sharpness",
    "lesion",                       # lesion scan: values are "none", "group:<group>", "type:<cell type>"
]

LESION_LABEL = r"^(none|group:.+|type:.+)$"


class SweepRequest(BaseModel):
    """Run `base` once per value of `parameter`, `repeats` times each (with
    seeds base.seed, base.seed + 1, ...) to measure the spread."""
    base: ConditioningRequest = Field(default_factory=ConditioningRequest)
    parameter: SweepParameter
    values: list[float | str] = Field(..., min_length=1, max_length=40)
    repeats: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def values_fit_parameter(self) -> "SweepRequest":
        import re
        if self.parameter == "lesion":
            bad = [v for v in self.values if not (isinstance(v, str) and re.match(LESION_LABEL, v))]
            if bad:
                raise ValueError(f'lesion values are "none", "group:<group>" or "type:<cell type>"; got {bad[:3]}')
        else:
            if any(isinstance(v, str) for v in self.values):
                raise ValueError(f"{self.parameter} values must be numbers")
            if len(self.values) > 25:
                raise ValueError("a numeric sweep has at most 25 values")
        return self


class SweepCounts(BaseModel):
    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0


class SweepSummary(BaseModel):
    id: str
    created_at: datetime
    parameter: SweepParameter
    values: list[float | str]
    repeats: int
    total: int
    counts: SweepCounts
    # done: finished with at least one result; failed / cancelled: finished with none
    status: Literal["running", "done", "failed", "cancelled"]
    base: ConditioningRequest


class MetricStats(BaseModel):
    mean: float | None
    std: float | None               # sample standard deviation (None if fewer than 2)
    n: int


class SweepPoint(BaseModel):
    value: float | str
    done: int
    metrics: dict[str, MetricStats]


class SweepPage(BaseModel):
    items: list[SweepSummary]
    next_cursor: str | None


class SweepCancelResult(BaseModel):
    cancelled: int                  # queued experiments that will not run
    stopping: int                   # running ones that stop at their next presentation


class SweepDetail(SweepSummary):
    metrics: list[str]              # names used in points[].metrics, in display order
    points: list[SweepPoint]