// compare.ts — two experiments side by side: which settings differ, and how the outcomes
// and the learning in each output-neuron type differ (e.g. intact vs lesioned).

import type { ExperimentDetail, ExperimentSummary } from "../types";
import { el, formatNumber, formatPercent } from "./dom";
import { describeExperiment } from "./history";

export interface SettingDiff {
  field: string;          // dotted path, e.g. "params.graded_gain"
  a: string;
  b: string;
}

function flatten(value: unknown, path: string, out: Map<string, string>): void {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) flatten(v, path ? `${path}.${k}` : k, out);
  } else {
    // drop null fields inside values: {"group":"APL","cell_type":null} reads as {"group":"APL"}
    out.set(path, value === null || value === undefined ? "default"
      : JSON.stringify(value, (_k, v: unknown) => (v === null ? undefined : v)));
  }
}

/** Request fields whose values differ between two experiments (absent = "default"). */
export function requestDiff(a: object, b: object): SettingDiff[] {
  const fa = new Map<string, string>(), fb = new Map<string, string>();
  flatten(a, "", fa);
  flatten(b, "", fb);
  const fields = [...new Set([...fa.keys(), ...fb.keys()])].sort();
  return fields
    .map((field) => ({ field, a: fa.get(field) ?? "default", b: fb.get(field) ?? "default" }))
    .filter((d) => d.a !== d.b && !(d.field === "seed"));   // seeds differ by design; shown separately
}

export interface MetricRow {
  label: string;
  a: number | null;
  b: number | null;
  percent: boolean;
}

export function metricRows(a: ExperimentDetail, b: ExperimentDetail): MetricRow[] {
  const ra = a.result!, rb = b.result!;
  const pi = (r: typeof ra) => (r.behavior.valid ? r.behavior.performance_index : null);
  return [
    { label: "Performance index (T-maze)", a: pi(ra), b: pi(rb), percent: false },
    { label: "CS+ change, US compartments", a: ra.compartment_change.cs_plus, b: rb.compartment_change.cs_plus, percent: true },
    { label: "CS− change, US compartments", a: ra.compartment_change.cs_minus, b: rb.compartment_change.cs_minus, percent: true },
    { label: "Kenyon cells active (CS+)", a: ra.separation.kc_active_plus, b: rb.separation.kc_active_plus, percent: false },
    { label: "Odour similarity at Kenyon cells", a: ra.separation.kc_correlation, b: rb.separation.kc_correlation, percent: false },
    { label: "Mean plastic weight (of initial)", a: ra.mean_weight_ratio, b: rb.mean_weight_ratio, percent: false },
  ];
}

/** Mean KC -> MBON weight (fraction of initial) per MBON type in A and B, largest difference first. */
export function mbonLearning(a: ExperimentDetail, b: ExperimentDetail, limit = 12):
    { cell_type: string; a: number; b: number }[] {
  const mean = (d: ExperimentDetail) => {
    const acc = new Map<string, { sum: number; n: number }>();
    for (const w of d.result!.mbon_weights) {
      const e = acc.get(w.cell_type) ?? { sum: 0, n: 0 };
      e.sum += w.weight_ratio;
      e.n += 1;
      acc.set(w.cell_type, e);
    }
    return new Map([...acc].map(([t, e]) => [t, e.sum / e.n]));
  };
  const ma = mean(a), mb = mean(b);
  return [...ma.keys()].filter((t) => mb.has(t))
    .map((t) => ({ cell_type: t, a: ma.get(t)!, b: mb.get(t)! }))
    .sort((x, y) => Math.abs(y.b - y.a) - Math.abs(x.b - x.a))
    .slice(0, limit);
}

function fmt(v: number | null, percent: boolean): string {
  if (v === null || !Number.isFinite(v)) return "n/a";
  return percent ? formatPercent(v) : formatNumber(v);
}

function table(head: string[], rows: string[][]): HTMLTableElement {
  return el("table", { class: "compare-table" }, [
    el("thead", {}, [el("tr", {}, head.map((h) => el("th", { text: h })))]),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el(i ? "td" : "th", { text: c }))))),
  ]);
}

/** "Compare with…" menu of other finished, stand-alone experiments. */
export function compareMenu(choices: ExperimentSummary[], currentId: string,
                            onPick: (id: string) => void): HTMLSelectElement | null {
  const others = choices.filter((e) => e.id !== currentId && e.status === "done" && !e.sweep_id);
  if (!others.length) return null;
  const select = el("select", { class: "compare-menu", title: "compare this experiment with another" });
  const first = el("option", { text: "Compare with…" });
  first.value = "";
  select.append(first, ...others.map((e) => Object.assign(el("option", { text: describeExperiment(e) }), { value: e.id })));
  select.addEventListener("change", () => { if (select.value) onPick(select.value); });
  return select;
}

export function renderComparison(root: HTMLElement, a: ExperimentDetail, b: ExperimentDetail,
                                 onBack: () => void): void {
  const back = el("button", { class: "link-button", text: "← back to A" });
  back.type = "button";
  back.addEventListener("click", onBack);
  const diffs = requestDiff(a.request, b.request);
  const metrics = metricRows(a, b);
  const learning = mbonLearning(a, b);
  root.replaceChildren(
    el("h2", { text: "Comparison" }),
    back,
    el("p", { class: "small" }, [el("strong", { text: "A " }), describeExperiment(a)]),
    el("p", { class: "small" }, [el("strong", { text: "B " }), describeExperiment(b)]),
    el("h3", { text: "What differs" }),
    diffs.length ? table(["setting", "A", "B"], diffs.map((d) => [d.field, d.a, d.b]))
      : el("p", { class: "muted small", text: "Same settings (only the random seed may differ)." }),
    ...(a.request.seed !== b.request.seed
      ? [el("p", { class: "muted small", text: `Seeds ${a.request.seed} and ${b.request.seed}: some difference is ` +
                                                "chance; repeat with a sweep to measure the spread." })] : []),
    el("h3", { text: "Outcomes" }),
    table(["", "A", "B", "B − A"], metrics.map((m) => [
      m.label, fmt(m.a, m.percent), fmt(m.b, m.percent),
      m.a !== null && m.b !== null ? fmt(m.b - m.a, m.percent) : "n/a",
    ])),
    el("h3", { text: "Learning per output-neuron type" }),
    el("p", { class: "muted small", text: "Mean KC → MBON weight after the experiment, as a fraction of " +
                                          "its initial value; largest differences first." }),
    table(["MBON type", "A", "B", "B − A"], learning.map((l) => [
      l.cell_type, formatNumber(l.a), formatNumber(l.b), formatNumber(l.b - l.a)])),
  );
}
