// types.ts — TypeScript mirror of backend/app/schemas.py.
// Keep in sync when the API changes; src/api.contract.test.ts checks a live server.

export type ExperimentStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type UsName = "none" | "shock" | "reward";
export type Phase = "pre" | "training" | "post";

export interface Health {
  status: string;
  neurons: number;
  odours_loaded: boolean;
  queue: "thread" | "redis";
  queue_ok: boolean;
  database: string;
  auth_required: boolean;        // writes need an X-API-Key header
  rate_limit_per_min: number;    // experiments per client per minute; 0 = none
}

export interface Partner {
  cell_type: string;
  group: string;
  neurons: number;
  synapses: number;
  sign: "excitatory" | "inhibitory" | "modulatory";
}

/** GET /api/circuit/neurons/{index} */
export interface NeuronDetail {
  index: number;
  root_id: string;              // the model's id
  flywire_id: string;           // FlyWire's id (differs for units standing for part of a neuron)
  region: string;               // e.g. "ML" for a regional APL unit; "" for a whole neuron
  group: string;
  cell_type: string;
  side: string;
  transmitter: string;
  graded: boolean;
  input_synapses: number;
  output_synapses: number;
  inputs: Partner[];
  outputs: Partner[];
}

/** GET /api/experiments/{id}/neurons/{index} */
export interface NeuronActivity {
  index: number;
  total_spikes: number;
  presentations: { label: string; phase: string; us: "none" | "shock" | "reward";
                   t_start_ms: number; t_end_ms: number; spikes: number; rate_hz: number }[];
}

export interface CircuitSummary {
  circuit_dir: string;
  neurons: number;
  fast_synapses: number;
  plastic_synapses: number;
  groups: Record<string, number>;
  mbons_with_ppl1_dopamine: number;
  mbons_with_pam_dopamine: number;
  odours_loaded: boolean;
  default_params?: Record<string, number | string | boolean>;
  anatomy?: Anatomy;                // missing on older servers
}

/** Which drawing aids the circuit has (scripts/build_anatomy.py). */
export interface Anatomy {
  regions: boolean;                 // brain region meshes
  morphology: boolean;              // neuron shapes
}

/** Column-oriented: element i of every array describes neuron index i. */
export interface NeuronTable {
  count: number;
  root_id: string[];          // strings: FlyWire IDs exceed Number.MAX_SAFE_INTEGER
  flywire_id?: string[];      // the FlyWire neuron a unit belongs to (its shape); missing on older servers
  group: string[];
  cell_type: string[];
  x: (number | null)[];
  y: (number | null)[];
  z: (number | null)[];
  bounds: { min: number[]; max: number[] } | null;
  groups: string[];
}

export interface OdourListItem {
  name: string;
  coverage: number;
}

export interface OdourCatalogItem {
  name: string;
  chemical_class: string;     // e.g. "esters"; "unclassified" when DoOR gives none
  coverage: number;           // share of receptors measured, 0..1
}

export interface OdourSimilarity {
  a: string;
  b: string;
  similarity: number | null;  // correlation of the receptor responses; null if not computable
}

export interface OdourList {
  total: number;
  offset: number;
  limit: number;
  items: OdourListItem[];
}

export interface ParamOverrides {
  graded_gain?: number;
  learning_rate?: number;
  plasticity_on?: boolean;
  tau_elig_ms?: number;
  tau_da_ms?: number;
  plasticity_rule?: "overlap" | "timing";
  timing_depression?: number;
  timing_potentiation?: number;
  prediction_error?: boolean;   // dopamine neurons also signal omitted expected USs (extinction)
  pe_gain_hz?: number;
  pe_us?: boolean;              // an expected US releases less dopamine (Rescorla-Wagner; blocking)
  pe_expectation?: "average" | "sum";   // "sum": cues present add their predictions (Rescorla-Wagner)
  pe_omission?: "separate" | "net";     // "net": omitted US signals the net (shock - reward) expectation
  pe_ref_active_frac?: number;  // "sum" asymptote: fraction of KCs one odour activates
  mbon_tonic_mV?: number;       // constant depolarising input to MBONs (spontaneous firing)
  mbon_tonic_by_type?: Record<string, number>;   // per MBON cell type (calibrated)
  graded_input_gain?: number;   // scale on input to graded neurons (APL); calibrated
  apl_plasticity?: boolean;     // dopamine suppresses KC -> APL input (Zhou et al. 2019)
  kc_dan_gain?: number;         // circuit loaded with kc_dan "terminal": KC gain on dopamine release
  mixture?: "linear" | "binding";   // compounds: odours compete for receptors (binding) or add (linear)
}

export interface ProtocolSettings {
  stim_ms?: number;
  gap_ms?: number;
  settle_ms?: number;
  us_hz?: number;
}

export interface BehaviorSettings {
  sharpness?: number;       // how strongly drive differences decide the choice (default 6)
  flies?: number;           // flies per simulated group (default 100)
}

export type Slot = "A" | "B" | "C" | "D";

/** One protocol step. us_onset_ms is relative to odour onset; negative = US first. */
export interface ProtocolStep {
  phase: string;
  odour?: string | null;        // a slot ("A") or a compound presented together ("A+C")
  us?: UsName;
  odour_ms?: number | null;
  us_onset_ms?: number;
  us_ms?: number | null;
  gap_ms?: number | null;
  repeat?: number;
}

export interface Readout {
  plus: Slot;
  minus: Slot;
  before: string;
  after: string;
}

export interface Lesion {
  group?: string;
  cell_type?: string;
}

export interface ProtocolPreset {
  name: string;
  title: string;
  description: string;
  in_flies: string;
  in_model: string;
  steps: ProtocolStep[];
  readout: Readout;
  params: ParamOverrides;
  extra_odour_slots: string[];
}

export interface LesionOptions {
  groups: string[];
  cell_types: string[];
}

export interface ConditioningRequest {
  cs_plus: string;
  cs_minus: string;
  odour_source: "door" | "random";
  trials: number;
  us: "shock" | "reward";
  seed: number;
  params?: ParamOverrides;
  protocol?: ProtocolSettings;
  behavior?: BehaviorSettings;
  steps?: ProtocolStep[] | null;              // null/absent = classic protocol from `trials`
  extra_odours?: Partial<Record<"C" | "D", string>>;
  readout?: Readout;
  lesions?: Lesion[];
}

export interface Separation {
  pn_correlation: number | null;
  kc_correlation: number | null;
  kc_active_plus: number;
  kc_active_minus: number;
  kc_shared: number;
}

export interface MbonSummary {
  cell_type: string;
  n: number;
  us_target: boolean;
  pre_plus: number;
  post_plus: number;
  pre_minus: number;
  post_minus: number;
}

export interface CompartmentChange {
  valid: boolean;
  cs_plus: number | null;
  cs_minus: number | null;
}

export interface MbonWeight {
  index: number;
  cell_type: string;
  weight_ratio: number;
}

export interface TimelineEntry {
  label: string;                 // odour name, or "US" for a US-only step
  slot: string | null;
  us: UsName;
  phase: Phase | string;         // "pre" / "training" / "post", or a protocol's own phase names
  t_start_ms: number;
  t_end_ms: number;
  us_start_ms: number | null;    // US window (may lie before the odour: backward pairing)
  us_end_ms: number | null;
}

export interface TMazeChoice {
  drive_plus: number | null;     // approach drive, -1 (avoid) .. +1 (approach)
  drive_minus: number | null;
  p_plus: number;                // probability of entering the CS+ arm
  preference: number;            // p(CS+) - p(CS-)
}

export interface Behavior {
  valid: boolean;                // false: no prediction possible (see valenced_mbons)
  valenced_mbons: number;        // output neurons with a known approach/avoid valence
  naive: TMazeChoice;
  trained: TMazeChoice;
  learned_drive: number | null;  // null when not valid
  performance_index: number | null;  // (-1, 1); positive = learned as the US teaches
  flies: number;
  sampled_performance_index: number | null;
}

export interface ExperimentResult {
  separation: Separation;
  mbons: MbonSummary[];
  compartment_change: CompartmentChange;
  mean_weight_ratio: number | null;
  mbon_weights: MbonWeight[];
  timeline: TimelineEntry[];
  duration_ms: number;
  n_spikes: number;
  coverage: Record<string, number> | null;
  input_similarity: number | null;
  behavior: Behavior;
  readout: Readout;
  readout_after_ms: number;      // when the "after" readout presentations start
  odours: Record<string, string>; // slot -> odour name
  lesioned: number[];            // silenced neuron indices
}

export interface Progress {
  done: number;       // odour presentations finished
  total: number;
}

export interface ExperimentSummary {
  id: string;
  sweep_id: string | null;            // set for experiments created by a sweep
  status: ExperimentStatus;
  progress: Progress | null;          // null until the simulation starts
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  request: Required<Omit<ConditioningRequest, "params" | "protocol" | "behavior">> & {
    params: ParamOverrides;
    protocol: Required<ProtocolSettings>;
    behavior: Required<BehaviorSettings>;
  };
  error: string | null;
}

export interface ExperimentDetail extends ExperimentSummary {
  result: ExperimentResult | null;
}

/** One page of a list, newest first; pass next_cursor back as `cursor` (null: last page). */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface CancelResult {
  status: ExperimentStatus;           // "cancelled", or "running" until the worker stops
}

/** Spikes with t0 <= t < t1, sorted by time; neurons[i] fired at times_ms[i]. */
export interface SpikeWindow {
  t0_ms: number;
  t1_ms: number;
  count: number;
  truncated: boolean;
  neurons: number[];
  times_ms: number[];
}

// ------------------------------------------------------------------ sweeps

export type SweepParameter =
  | "params.graded_gain" | "params.learning_rate" | "params.tau_elig_ms" | "params.tau_da_ms"
  | "protocol.us_hz" | "protocol.stim_ms" | "trials" | "behavior.sharpness"
  | "lesion";                    // lesion scan: values "none", "group:<group>", "type:<cell type>"

/** A swept value: a number, or a lesion label for lesion scans. */
export type SweepValue = number | string;

export interface SweepRequest {
  base: ConditioningRequest;
  parameter: SweepParameter;
  values: SweepValue[];
  repeats: number;
}

export interface SweepCounts {
  queued: number;
  running: number;
  done: number;
  failed: number;
  cancelled: number;
}

export interface SweepCancelResult {
  cancelled: number;           // queued experiments that will not run
  stopping: number;            // running ones that stop at their next presentation
}

export interface SweepSummary {
  id: string;
  created_at: string;
  parameter: SweepParameter;
  values: SweepValue[];
  repeats: number;
  total: number;
  counts: SweepCounts;
  status: "running" | "done" | "failed" | "cancelled";   // failed/cancelled: finished with no results
  base: ExperimentSummary["request"];
}

export interface MetricStats {
  mean: number | null;
  std: number | null;          // sample SD; null with fewer than 2 values
  n: number;
}

export interface SweepPoint {
  value: SweepValue;
  done: number;
  metrics: Record<string, MetricStats>;
}

export interface SweepDetail extends SweepSummary {
  metrics: string[];
  points: SweepPoint[];
}
// ---------------------------------------------------------------- connections and anatomy

export type SynapseSign = "excitatory" | "inhibitory" | "modulatory";

export interface Connection {
  index: number;              // the partner neuron
  synapses: number;
  sign: SynapseSign;
}

/** Every partner of one neuron (fast synapses, strongest first), and dopamine coupling. */
export interface NeuronConnections {
  index: number;
  min_synapses: number;
  total_inputs: number;
  total_outputs: number;
  inputs: Connection[];
  outputs: Connection[];
  dopamine_to: number[];      // a DAN: the MBONs its dopamine reaches
  dopamine_from: number[];    // an MBON: the DANs whose dopamine reaches it
}

export interface GroupConnection {
  pre: string;
  post: string;
  synapses: number;           // 0 for dopamine coupling
  connections: number;        // connected neuron pairs
  sign: SynapseSign | "mixed" | "dopamine";
}

/** One brain region mesh, in FlyWire space (nm). */
export interface BrainRegion {
  name: string;               // e.g. "MB_CA_R"
  region: string;             // e.g. "MB_CA"
  side: "left" | "right" | "center";
  label: string;              // e.g. "mushroom body calyx"
  olfactory: boolean;         // on the odour pathway: drawn more strongly and labelled
  vertices: number[];         // x, y, z, x, y, z, ...
  triangles: number[];        // vertex indices, three per triangle
}

export interface BrainRegions {
  units: string;
  regions: BrainRegion[];
}
