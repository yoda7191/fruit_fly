// results.ts — the learning outcome of one experiment, in words and numbers.

import type {
  ExperimentResult,
  Behavior,
  CompartmentChange,
  ExperimentDetail,
  LearningCurvePoint,
  WeightStats,
  PopulationStats,
  Prediction,
} from "../types";
import { el, formatNumber, formatPercent } from "./dom";

const SVG_NS = "http://www.w3.org/2000/svg";

function createSvg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number>,
  text?: string
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = text;
  return node;
}

function learningCurveSection(lc: LearningCurvePoint[], plusSlot: string, minusSlot: string): HTMLElement[] {
  if (!lc.length) return [];
  const w = 320, h = 130;
  const m = { top: 15, right: 15, bottom: 25, left: 35 };
  const pw = w - m.left - m.right;
  const ph = h - m.top - m.bottom;

  const plusPoints = lc.filter((p) => p.slot === plusSlot);
  const minusPoints = lc.filter((p) => p.slot === minusSlot);
  const maxTrial = Math.max(1, ...lc.map((p) => p.trial));
  const maxSpikes = Math.max(1, ...lc.map((p) => Math.max(p.mbon_spikes, p.mbon_all_spikes)));

  const scaleX = (trial: number) => m.left + ((trial - 1) / Math.max(1, maxTrial - 1)) * pw;
  const scaleY = (spikes: number) => m.top + ph - (spikes / maxSpikes) * ph;

  const svg = createSvg("svg", { viewBox: `0 0 ${w} ${h}`, class: "sweep-chart" });
  svg.appendChild(createSvg("line", { x1: m.left, y1: m.top + ph, x2: m.left + pw, y2: m.top + ph, class: "grid" }));
  svg.appendChild(createSvg("line", { x1: m.left, y1: m.top, x2: m.left, y2: m.top + ph, class: "grid" }));

  svg.appendChild(createSvg("text", { x: m.left - 4, y: m.top + 10, "text-anchor": "end", class: "tick" }, maxSpikes.toFixed(0)));
  svg.appendChild(createSvg("text", { x: m.left - 4, y: m.top + ph, "text-anchor": "end", class: "tick" }, "0"));
  svg.appendChild(createSvg("text", { x: m.left + pw / 2, y: h - 5, "text-anchor": "middle", class: "tick" }, "Training trials"));

  if (plusPoints.length > 0) {
    const dPlus = plusPoints.map((p) => `${scaleX(p.trial)},${scaleY(p.mbon_spikes)}`).join(" ");
    svg.appendChild(createSvg("polyline", { points: dPlus, fill: "none", stroke: "var(--neg, #a78bfa)", "stroke-width": 2 }));
    for (const p of plusPoints) {
      svg.appendChild(createSvg("circle", { cx: scaleX(p.trial), cy: scaleY(p.mbon_spikes), r: 3.5, fill: "var(--neg, #a78bfa)" }));
    }
  }

  if (minusPoints.length > 0) {
    const dMinus = minusPoints.map((p) => `${scaleX(p.trial)},${scaleY(p.mbon_spikes)}`).join(" ");
    svg.appendChild(createSvg("polyline", {
      points: dMinus, fill: "none", stroke: "var(--accent, #60a5fa)", "stroke-width": 2, "stroke-dasharray": "4 3"
    }));
    for (const p of minusPoints) {
      svg.appendChild(createSvg("circle", { cx: scaleX(p.trial), cy: scaleY(p.mbon_spikes), r: 3, fill: "var(--accent, #60a5fa)" }));
    }
  }

  const legend = el("div", { class: "small muted", style: "display: flex; gap: 1rem; margin-top: 0.3rem;" }, [
    el("span", {}, [el("span", { style: "color: var(--neg, #a78bfa); font-weight: bold;", text: "— " }), "CS+ (target MBONs)"]),
    el("span", {}, [el("span", { style: "color: var(--accent, #60a5fa); font-weight: bold;", text: "- - " }), "CS\u2212"]),
  ]);

  return [
    el("h3", { text: "Learning curve (target output neurons)" }),
    el("div", {}, [svg]),
    legend,
  ];
}

function weightDistributionSection(ws: WeightStats): HTMLElement[] {
  if (!ws.histogram?.length) return [];
  const w = 320, h = 95;
  const m = { top: 10, right: 10, bottom: 22, left: 30 };
  const pw = w - m.left - m.right;
  const ph = h - m.top - m.bottom;

  const maxCount = Math.max(1, ...ws.histogram.map((b) => b.count));
  const barW = Math.max(2, pw / ws.histogram.length - 2);

  const svg = createSvg("svg", { viewBox: `0 0 ${w} ${h}`, class: "sweep-chart" });
  svg.appendChild(createSvg("line", { x1: m.left, y1: m.top + ph, x2: m.left + pw, y2: m.top + ph, class: "grid" }));

  ws.histogram.forEach((b, i) => {
    const barH = (b.count / maxCount) * ph;
    const x = m.left + i * (pw / ws.histogram.length) + 1;
    const y = m.top + ph - barH;
    svg.appendChild(createSvg("rect", {
      x, y, width: barW, height: barH, fill: "var(--pos, #34d399)", rx: 1
    }));
  });

  svg.appendChild(createSvg("text", { x: m.left, y: h - 4, class: "tick" }, "0.0"));
  svg.appendChild(createSvg("text", { x: m.left + pw / 2, y: h - 4, "text-anchor": "middle", class: "tick" }, "w / w0 ratio"));
  svg.appendChild(createSvg("text", { x: m.left + pw, y: h - 4, "text-anchor": "end", class: "tick" }, "1.0"));

  const stats = [
    `Mean: ${formatNumber(ws.mean)}`,
    `Median: ${formatNumber(ws.median)}`,
    ws.floor_fraction !== null ? `At floor: ${formatPercent(ws.floor_fraction)}` : null,
  ].filter(Boolean).join(" \u00b7 ");

  return [
    el("h3", { text: "Synaptic weight change distribution" }),
    el("div", {}, [svg]),
    el("p", { class: "small muted", text: stats }),
  ];
}

function populationSection(ps: PopulationStats): HTMLElement[] {
  const elements: HTMLElement[] = [];

  if (ps.groups && ps.groups.length > 0) {
    elements.push(el("h3", { text: "Population firing rates (post-training)" }));
    const rows = ps.groups.map((g) =>
      row(`${g.group} (CS+ / CS\u2212)`, `${g.post_plus_hz.toFixed(1)} / ${g.post_minus_hz.toFixed(1)} Hz`)
    );
    elements.push(el("table", { class: "kv" }, rows));
  }

  if (ps.kc_sparseness) {
    const ks = ps.kc_sparseness;
    const pctPlus = ks.total_kc > 0 ? ((ks.active_plus_count / ks.total_kc) * 100).toFixed(1) : "0";
    const pctMinus = ks.total_kc > 0 ? ((ks.active_minus_count / ks.total_kc) * 100).toFixed(1) : "0";
    const sparsenessRows = [
      row("Active Kenyon cells (CS+)", `${ks.active_plus_count} (${pctPlus}%)`),
      row("Active Kenyon cells (CS\u2212)", `${ks.active_minus_count} (${pctMinus}%)`),
      ks.treves_rolls_plus !== null ? row("Treves-Rolls sparseness", `${formatNumber(ks.treves_rolls_plus)} (lower = sparser)`) : null,
      ps.mbon_discrimination !== null && ps.mbon_discrimination !== undefined
        ? row("MBON odour discrimination", formatNumber(ps.mbon_discrimination))
        : null,
    ].filter((r): r is HTMLTableRowElement => r !== null);
    elements.push(el("h3", { text: "Kenyon cell coding sparseness" }));
    elements.push(el("table", { class: "kv" }, sparsenessRows));
  }

  return elements;
}

function predictionSection(pred: Prediction): HTMLElement[] {
  const rows = [];
  if (pred.expected_shock !== null) {
    rows.push(row("Expected shock", formatNumber(pred.expected_shock)));
  }
  if (pred.expected_reward !== null) {
    rows.push(row("Expected reward", formatNumber(pred.expected_reward)));
  }
  if (!rows.length) return [];
  return [
    el("h3", { text: "Learned US expectation (prediction error)" }),
    el("table", { class: "kv" }, rows),
  ];
}

export type Verdict = "specific" | "generalized" | "weak" | "none";

/** Thresholds match the backend tests: a real effect is a drop of 20% or more. */
export function interpret(cc: CompartmentChange): { verdict: Verdict; text: string } {
  if (!cc.valid || cc.cs_plus === null || cc.cs_minus === null) {
    return { verdict: "none",
             text: "The output neurons that receive the US dopamine never fired, so no change can be measured." };
  }
  if (cc.cs_plus > -0.2) {
    return { verdict: "weak",
             text: "Little learning: the trained odour's response barely changed. Try more trials or a higher learning rate." };
  }
  if (cc.cs_minus <= -0.2) {
    return { verdict: "generalized",
             text: "Generalization: the untrained odour's response also dropped, because the two odours activate overlapping Kenyon cells." };
  }
  return { verdict: "specific",
           text: "Odour-specific memory: only the trained odour's response dropped." };
}

/** Why no T-maze prediction could be made (behavior.valid is false). */
export function noPredictionReason(b: Pick<Behavior, "valenced_mbons">): string {
  return b.valenced_mbons === 0
    ? "No output neuron has a known transmitter, so approach and avoidance can't be told apart. " +
      "Re-extract the circuit with scripts/extract_mb_circuit.py, which records each neuron's transmitter."
    : "The output neurons with a known valence didn't fire for both odours, so there is nothing to compare.";
}

/** How to read a performance index, in the terms fly researchers use. */
export function describePI(pi: number): string {
  const a = Math.abs(pi);
  if (a < 0.15) return "no clear learning";
  const strength = a >= 0.6 ? "strong" : a >= 0.3 ? "moderate" : "weak";
  return pi > 0 ? `${strength} learning` : `${strength} learning in the wrong direction`;
}

function behaviorSection(b: Behavior, csPlus: string, csMinus: string, us: string): HTMLElement[] {
  if (!b.valid || b.performance_index === null) {
    return [
      el("h3", { text: "Predicted behaviour in a T-maze" }),
      el("p", { class: "verdict none", text: `No prediction. ${noPredictionReason(b)}` }),
    ];
  }
  const toward = us === "reward" ? "toward" : "away from";
  const pct = (p: number) => `${Math.round(p * 100)}%`;
  const split = el("div", { class: "choice-bar", title: "predicted choices after training" }, [
    el("div", { class: "arm plus", text: `CS+ ${pct(b.trained.p_plus)}` }),
    el("div", { class: "arm minus", text: `CS\u2212 ${pct(1 - b.trained.p_plus)}` }),
  ]);
  (split.firstElementChild as HTMLElement).style.flexBasis = pct(b.trained.p_plus);
  return [
    el("h3", { text: "Predicted behaviour in a T-maze" }),
    el("p", { class: "pi" }, [
      el("span", { class: "pi-value", text: formatNumber(b.performance_index) }),
      el("span", { class: "pi-label",
                   text: ` performance index \u00b7 ${describePI(b.performance_index)} (${toward} ${csPlus})` }),
    ]),
    el("p", { class: "muted small",
              text: `A simulated group of ${b.flies} flies scores ${formatNumber(b.sampled_performance_index)} ` +
                    `(${b.valenced_mbons} output neurons with a valence). ` +
                    "1 = every fly chooses as trained, 0 = no learning." }),
    el("p", { class: "small", text: "Choices after training (includes any innate odour preference):" }),
    split,
    el("table", { class: "kv" }, [
      row(`Approach drive of ${csPlus}`, `${formatNumber(b.naive.drive_plus)} \u2192 ${formatNumber(b.trained.drive_plus)}`),
      row(`Approach drive of ${csMinus}`, `${formatNumber(b.naive.drive_minus)} \u2192 ${formatNumber(b.trained.drive_minus)}`),
    ]),
    el("p", { class: "muted small",
              text: "Drive is the balance of approach (cholinergic, GABAergic) and avoidance (glutamatergic) " +
                    "output neurons (Aso et al. 2014b), from \u22121 to +1. Innate odour bias is subtracted, " +
                    "as in reciprocal T-maze experiments." }),
  ];
}

function bar(label: string, value: number | null): HTMLElement {
  const width = value === null ? 0 : Math.min(1, Math.abs(value)) * 100;
  const fill = el("div", { class: `fill ${value !== null && value < 0 ? "neg" : "pos"}` });
  fill.style.width = `${width}%`;
  return el("div", { class: "bar-row" }, [
    el("span", { class: "bar-label", text: label, title: label }),
    el("div", { class: "bar" }, [fill]),
    el("span", { class: "bar-value", text: formatPercent(value) }),
  ]);
}

export function renderResults(root: HTMLElement, detail: ExperimentDetail): void {
  const res = detail.result;
  if (!res) {
    root.replaceChildren(el("p", { class: "muted", text: "No result yet." }));
    return;
  }
  const req = detail.request;
  const cc = res.compartment_change;
  const { verdict, text } = interpret(cc);
  const usLabel = req.us === "shock" ? "shock (PPL1)" : "reward (PAM)";

  const sections: HTMLElement[] = [
    el("h2", { text: "Result" }),
    el("p", { class: "muted",
              text: `${req.trials} trial${req.trials === 1 ? "" : "s"} \u00b7 US: ${usLabel} \u00b7 ` +
                    `${(res.duration_ms / 1000).toFixed(1)} s simulated \u00b7 ${res.n_spikes.toLocaleString()} spikes` }),
    ...protocolLines(res),
    el("h3", { text: "Change in US-innervated output neurons" }),
    bar(`CS+ ${req.cs_plus}`, cc.cs_plus),
    bar(`CS\u2212 ${req.cs_minus}`, cc.cs_minus),
    el("p", { class: `verdict ${verdict}`, text }),
    ...behaviorSection(res.behavior, req.cs_plus, req.cs_minus, req.us),
  ];

  if (res.learning_curve && res.learning_curve.length > 0) {
    sections.push(...learningCurveSection(res.learning_curve, res.readout.plus, res.readout.minus));
  }

  if (res.weight_stats) {
    sections.push(...weightDistributionSection(res.weight_stats));
  }

  const sep = res.separation;
  sections.push(
    el("h3", { text: "Odour representations (before training)" }),
    el("table", { class: "kv" }, [
      row("Similarity at projection neurons", formatNumber(sep.pn_correlation)),
      row("Similarity at Kenyon cells", formatNumber(sep.kc_correlation)),
      row("Kenyon cells active (CS+ / CS\u2212)",
          `${formatPercent(sep.kc_active_plus, false)} / ${formatPercent(sep.kc_active_minus, false)}`),
      row("Kenyon cells shared", String(sep.kc_shared)),
      res.input_similarity !== null ? row("Receptor-level similarity (DoOR)", formatNumber(res.input_similarity)) : null,
      res.coverage ? row("DoOR coverage (CS+ / CS\u2212)",
                         `${formatPercent(res.coverage[req.cs_plus] ?? null, false)} / ` +
                         `${formatPercent(res.coverage[req.cs_minus] ?? null, false)}`) : null,
    ]),
  );

  if (res.population_stats) {
    sections.push(...populationSection(res.population_stats));
  }

  const head = el("tr", {}, ["MBON", "US-DA", "CS+ pre", "CS+ post", "CS\u2212 pre", "CS\u2212 post"]
    .map((h) => el("th", { text: h })));
  const rows = res.mbons.map((m) =>
    el("tr", { class: m.us_target ? "target" : "" }, [
      el("td", { text: m.cell_type }),
      el("td", { text: m.us_target ? "\u25cf" : "" }),
      ...[m.pre_plus, m.post_plus, m.pre_minus, m.post_minus].map((v) => el("td", { text: v.toFixed(1) })),
    ]));
  sections.push(
    el("h3", { text: "Output neuron spikes per odour presentation" }),
    el("div", { class: "table-scroll" }, [el("table", { class: "mbons" }, [el("thead", {}, [head]), el("tbody", {}, rows)])]),
    el("p", { class: "muted small",
              text: "In the 3D view, output neurons turn from yellow to purple once training has ended, " +
                    "in proportion to how much their Kenyon cell inputs weakened." }),
  );

  if (res.prediction) {
    sections.push(...predictionSection(res.prediction));
  }

  root.replaceChildren(...sections);
}

function row(key: string, value: string): HTMLTableRowElement {
  return el("tr", {}, [el("th", { text: key }), el("td", { text: value })]);
}

/** Which presentations the numbers compare, and any lesion. */
export function protocolLines(res: ExperimentResult): HTMLElement[] {
  const ro = res.readout;
  const name = (slot: string) => res.odours[slot] ?? slot;
  const lines: HTMLElement[] = [];
  if (ro.before !== "pre" || ro.after !== "post" || ro.plus !== "A" || ro.minus !== "B") {
    lines.push(el("p", { class: "small",
      text: `Readout: ${name(ro.plus)} vs ${name(ro.minus)}, from phase "${ro.before}" to "${ro.after}".` }));
  }
  if (res.lesioned.length) {
    lines.push(el("p", { class: "small lesion-note",
      text: `${res.lesioned.length} neuron${res.lesioned.length === 1 ? "" : "s"} silenced (lesion); ` +
            "shown dark grey in 3D." }));
  }
  return lines;
}
/** "Download: result (JSON) · output neurons (CSV) · all spikes (CSV)". */
export function downloadLinks(urls: { json: string; mbons: string; spikes: string }): HTMLElement {
  const link = (href: string, text: string) =>
    Object.assign(el("a", { text }), { href, download: "" });
  return el("p", { class: "downloads small" }, [
    "Download: ", link(urls.json, "result (JSON)"), " \u00b7 ",
    link(urls.mbons, "output neurons (CSV)"), " \u00b7 ", link(urls.spikes, "all spikes (CSV)"),
  ]);
}
