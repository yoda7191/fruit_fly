// sweepPanel.ts — set up a parameter sweep from the current experiment settings.

import type { ConditioningRequest, LesionOptions, SweepParameter, SweepRequest, SweepSummary } from "../types";
import { byId } from "./dom";

export const SWEEP_PARAMETERS: { value: SweepParameter; label: string; example: string }[] = [
  { value: "params.graded_gain", label: "APL inhibition (gain)", example: "0, 0.025, 0.05, 0.1, 0.2" },
  { value: "trials", label: "training trials", example: "0, 1, 2, 3, 5" },
  { value: "protocol.us_hz", label: "US strength (dopamine neuron Hz)", example: "0, 10, 20, 40, 80" },
  { value: "params.learning_rate", label: "learning rate", example: "5e-7, 1e-6, 2e-6, 4e-6" },
  { value: "params.tau_elig_ms", label: "Kenyon cell memory window (ms)", example: "100, 300, 1000" },
  { value: "params.tau_da_ms", label: "dopamine duration (ms)", example: "100, 300, 1000" },
  { value: "protocol.stim_ms", label: "odour duration (ms)", example: "250, 500, 1000, 2000" },
  { value: "behavior.sharpness", label: "choice sharpness", example: "2, 4, 6, 10" },
  { value: "lesion", label: "lesion scan (silence one group or cell type)",
    example: "none, group:APL, group:DAN_PPL1, group:DAN_PAM" },
];

/** Groups tried first for the lesion scan example: the ones with known roles in learning. */
const EXAMPLE_LESION_GROUPS = ["APL", "DPM", "DAN_PPL1", "DAN_PAM"];

export function lesionExample(options?: LesionOptions): string {
  const groups = options?.groups.length
    ? EXAMPLE_LESION_GROUPS.filter((g) => options.groups.includes(g))
    : EXAMPLE_LESION_GROUPS;
  return ["none", ...groups.map((g) => `group:${g}`)].join(", ");
}

export function parameterLabel(p: string): string {
  return SWEEP_PARAMETERS.find((x) => x.value === p)?.label ?? p;
}

/** "0, 0.05; 0.1 0.2" -> [0, 0.05, 0.1, 0.2], or an error message. */
export function parseValues(text: string): number[] | string {
  const parts = text.split(/[\s,;]+/).filter((p) => p !== "");
  if (parts.length === 0) return "Enter at least one value.";
  if (parts.length > 25) return "At most 25 values.";
  const values: number[] = [];
  for (const p of parts) {
    const v = Number(p);
    if (!Number.isFinite(v)) return `"${p}" is not a number.`;
    if (values.includes(v)) return `${p} appears twice.`;
    values.push(v);
  }
  return values;
}

/** "none, group:APL, type:MBON01" -> labels, or an error message. Names are checked
 *  against `options` when given, so a typo fails here rather than as a failed sweep.
 *  Separated by commas or semicolons only: cell type names may contain spaces. */
export function parseLesionValues(text: string, options?: LesionOptions): string[] | string {
  const parts = text.split(/[,;\n]+/).map((p) => p.trim()).filter((p) => p !== "");
  if (parts.length === 0) return "Enter at least one lesion, e.g. none, group:APL.";
  if (parts.length > 40) return "At most 40 lesions.";
  const known = options && (options.groups.length || options.cell_types.length) ? options : undefined;
  const values: string[] = [];
  for (const p of parts) {
    const m = /^(group|type):(.+)$/.exec(p);
    if (p !== "none" && !m) return `"${p}": write none, group:<group> or type:<cell type>.`;
    if (m && known) {
      const list = m[1] === "group" ? known.groups : known.cell_types;
      if (!list.includes(m[2]!)) return `"${p}": no ${m[1] === "group" ? "group" : "cell type"} "${m[2]}" in this circuit.`;
    }
    if (values.includes(p)) return `${p} appears twice.`;
    values.push(p);
  }
  return values;
}

/** Final status line for a finished sweep. Partial failures are stated, not hidden:
 *  averages then come from the successful runs only (the CSV lists each error). */
export function sweepOutcome(s: Pick<SweepSummary, "total" | "counts">): { text: string; kind: "info" | "error" } {
  const { done, failed } = s.counts;
  const cancelled = s.counts.cancelled ?? 0;
  if (cancelled) {
    return { text: `Cancelled: ${done} of ${s.total} experiments finished` +
                   `${failed ? `, ${failed} failed` : ""}${done ? "; averages use those" : ""}.`, kind: "info" };
  }
  if (failed === 0) return { text: `All ${s.total} experiments finished.`, kind: "info" };
  if (done === 0) return { text: `All ${s.total} experiments failed; the CSV lists the errors.`, kind: "error" };
  return { text: `${done} of ${s.total} experiments finished, ${failed} failed. Averages use the ` +
                 "successful runs; the CSV lists the errors.", kind: "error" };
}

export interface SweepPanelOptions {
  getBase: () => ConditioningRequest | string;
  onSubmit: (req: SweepRequest) => void;
  onPick: (sweepId: string) => void;
  lesionOptions?: LesionOptions;      // checks lesion scan names; absent = format check only
}

export class SweepPanel {
  private readonly parameter = byId("sweep-parameter", HTMLSelectElement);
  private readonly values = byId("sweep-values", HTMLInputElement);
  private readonly repeats = byId("sweep-repeats", HTMLInputElement);
  private readonly button = byId("sweep-button", HTMLButtonElement);
  private readonly status = byId("sweep-status", HTMLParagraphElement);
  private readonly history = byId("sweep-history", HTMLSelectElement);

  constructor(private readonly opts: SweepPanelOptions) {
    this.parameter.replaceChildren(...SWEEP_PARAMETERS.map((p) => {
      const o = document.createElement("option");
      o.value = p.value;
      o.textContent = p.label;
      return o;
    }));
    this.parameter.addEventListener("change", () => this.showExample());
    this.showExample();
    this.button.addEventListener("click", () => {
      const req = this.read();
      if (typeof req === "string") this.setStatus(req, "error");
      else this.opts.onSubmit(req);
    });
    this.history.addEventListener("change", () => {
      if (this.history.value) this.opts.onPick(this.history.value);
    });
  }

  read(): SweepRequest | string {
    const base = this.opts.getBase();
    if (typeof base === "string") return base;
    const parameter = this.parameter.value as SweepParameter;
    const values = parameter === "lesion"
      ? parseLesionValues(this.values.value, this.opts.lesionOptions)
      : parseValues(this.values.value);
    if (typeof values === "string") return values;
    const repeats = Number(this.repeats.value);
    if (!Number.isInteger(repeats) || repeats < 1 || repeats > 10) return "Repeats must be 1 to 10.";
    return { base, parameter, values, repeats };
  }

  setBusy(busy: boolean): void {
    this.button.disabled = busy;
    this.button.textContent = busy ? "Sweep running\u2026" : "Run sweep";
  }

  setStatus(text: string, kind: "info" | "error" = "info"): void {
    this.status.textContent = text;
    this.status.className = `status ${kind}`;
  }

  setHistory(sweeps: SweepSummary[], selectedId: string | null): void {
    const first = document.createElement("option");
    first.value = "";
    first.textContent = sweeps.length ? "Previous sweeps\u2026" : "No previous sweeps";
    this.history.replaceChildren(first, ...sweeps.map((s) => {
      const o = document.createElement("option");
      o.value = s.id;
      const time = new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      o.textContent = `${time} \u00b7 ${parameterLabel(s.parameter)} \u00b7 ${s.values.length}\u00d7${s.repeats} \u00b7 ${s.status}`;
      return o;
    }));
    this.history.value = selectedId && sweeps.some((s) => s.id === selectedId) ? selectedId : "";
  }

  private showExample(): void {
    const p = SWEEP_PARAMETERS.find((x) => x.value === this.parameter.value);
    if (p) this.values.value = p.value === "lesion" ? lesionExample(this.opts.lesionOptions) : p.example;
  }
}