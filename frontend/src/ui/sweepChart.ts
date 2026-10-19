// sweepChart.ts — a sweep's result: one metric (mean ± SD) against the swept value.

import type { SweepDetail, SweepPoint, SweepValue } from "../types";
import { el, formatNumber } from "./dom";
import { parameterLabel } from "./sweepPanel";

export const METRIC_LABELS: Record<string, string> = {
  performance_index: "Performance index (T-maze)",
  cs_plus_change: "CS+ output change (US compartments)",
  cs_minus_change: "CS\u2212 output change (US compartments)",
  kc_active_plus: "Kenyon cells active for CS+",
  kc_correlation: "Odour similarity at Kenyon cells",
  pn_correlation: "Odour similarity at projection neurons",
};

const SVG = "http://www.w3.org/2000/svg";
const W = 340;
const H = 220;
const M = { top: 12, right: 12, bottom: 34, left: 44 };

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>,
                                                   text?: string): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Axis range covering all values plus 0, padded by 8%. */
export function extent(values: number[]): [number, number] {
  const finite = values.filter(Number.isFinite);
  let lo = Math.min(0, ...finite);
  let hi = Math.max(0, ...finite);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

export function ticks([lo, hi]: [number, number], count = 5): number[] {
  const step = (hi - lo) / (count - 1);
  return Array.from({ length: count }, (_, i) => lo + i * step);
}

function fmt(v: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  return a < 0.01 || a >= 10_000 ? v.toExponential(1) : Number(v.toPrecision(3)).toString();
}

/** Axis label of a swept value: numbers compactly, lesion labels by name ("none" -> "intact"). */
export function valueLabel(v: SweepValue): string {
  if (typeof v === "number") return fmt(v);
  return v === "none" ? "intact" : v.replace(/^(group|type):/, "");
}

export function renderSweepChart(points: SweepPoint[], metric: string): SVGSVGElement {
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "sweep-chart", role: "img" });
  // Lesion scans are categorical: evenly spaced, in request order, with no line
  // joining them (the order of lesions means nothing). Numeric sweeps use a linear axis.
  const categorical = points.some((p) => typeof p.value === "string");
  const rotate = categorical && points.length > 4;                // long names need room
  const bottom = rotate ? 70 : M.bottom;
  const stats = points.map((p, i) => ({ x: categorical ? i : Number(p.value), label: valueLabel(p.value),
                                        s: p.metrics[metric] }));
  const withMean = stats.filter((d) => d.s && d.s.mean !== null);
  const xs = stats.map((d) => d.x);
  const ys = withMean.flatMap((d) => [d.s!.mean! - (d.s!.std ?? 0), d.s!.mean! + (d.s!.std ?? 0)]);

  const [x0, x1] = categorical ? [-0.5, points.length - 0.5]
    : xs.length > 1 ? [Math.min(...xs), Math.max(...xs)] : [xs[0]! - 1, xs[0]! + 1];
  const yr = extent(ys);
  const sx = (v: number) => M.left + ((v - x0) / (x1 - x0 || 1)) * (W - M.left - M.right);
  const sy = (v: number) => H - bottom - ((v - yr[0]) / (yr[1] - yr[0])) * (H - M.top - bottom);

  // axes and grid
  for (const t of ticks(yr)) {
    root.append(svg("line", { x1: M.left, x2: W - M.right, y1: sy(t), y2: sy(t), class: "grid" }));
    root.append(svg("text", { x: M.left - 6, y: sy(t) + 4, "text-anchor": "end", class: "tick" }, fmt(t)));
  }
  root.append(svg("line", { x1: M.left, x2: W - M.right, y1: sy(0), y2: sy(0), class: "zero" }));
  for (const d of stats) {
    const x = sx(d.x);
    const y = H - bottom + 16;
    root.append(svg("text", rotate
      ? { x, y: y - 6, "text-anchor": "end", transform: `rotate(-40 ${x} ${y - 6})`, class: "tick" }
      : { x, y, "text-anchor": "middle", class: "tick" }, d.label));
  }

  if (withMean.length === 0) {
    root.append(svg("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" },
                    "no finished experiments yet"));
    return root;
  }

  // mean line, SD error bars, points
  if (!categorical) {
    const path = withMean.map((d, i) => `${i ? "L" : "M"}${sx(d.x)},${sy(d.s!.mean!)}`).join(" ");
    root.append(svg("path", { d: path, class: "mean-line" }));
  }
  for (const d of withMean) {
    const m = d.s!.mean!;
    if (d.s!.std !== null) {
      const top = sy(m + d.s!.std!);
      const bot = sy(m - d.s!.std!);
      root.append(svg("line", { x1: sx(d.x), x2: sx(d.x), y1: top, y2: bot, class: "error-bar" }));
      for (const y of [top, bot]) {
        root.append(svg("line", { x1: sx(d.x) - 4, x2: sx(d.x) + 4, y1: y, y2: y, class: "error-bar" }));
      }
    }
    const dot = svg("circle", { cx: sx(d.x), cy: sy(m), r: 4, class: "point" });
    dot.append(svg("title", {}, `${d.label}: ${formatNumber(m)}${d.s!.std !== null ? ` \u00b1 ${formatNumber(d.s!.std)}` : ""} (n = ${d.s!.n})`));
    root.append(dot);
  }
  return root;
}

export function renderSweep(root: HTMLElement, detail: SweepDetail, metric: string, csvUrl: string,
                            onMetric: (metric: string) => void): void {
  const finished = detail.counts.done + detail.counts.failed;
  const select = el("select", { title: "metric to plot" });
  for (const m of detail.metrics) {
    const o = el("option", { text: METRIC_LABELS[m] ?? m });
    o.value = m;
    o.selected = m === metric;
    select.append(o);
  }
  select.addEventListener("change", () => onMetric(select.value));
  const csv = el("a", { text: "Download CSV", class: "button-link" });
  csv.href = csvUrl;
  csv.setAttribute("download", "");

  root.replaceChildren(
    el("h2", { text: "Sweep" }),
    el("p", { class: "muted",
              text: `${parameterLabel(detail.parameter)} \u00b7 ${detail.values.length} values \u00d7 ` +
                    `${detail.repeats} seeds \u00b7 ${detail.base.cs_plus} vs ${detail.base.cs_minus}, ` +
                    `${detail.base.us}` }),
    el("p", { class: "status", text: `${finished} of ${detail.total} experiments finished` +
              (detail.counts.failed ? ` (${detail.counts.failed} failed)` : "") }),
    select,
    renderSweepChart(detail.points, metric),
    el("p", { class: "muted small",
              text: `x: ${parameterLabel(detail.parameter)}. Points are means over seeds; bars show \u00b1 1 SD.` }),
    csv,
  );
}