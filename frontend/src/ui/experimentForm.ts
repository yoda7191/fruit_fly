// experimentForm.ts — the experiment settings, in three steps: odours, training,
// manipulations (advanced settings folded away). Reads and validates the request.

import type { ConditioningRequest, ExperimentSummary, LesionOptions, OdourCatalogItem, ProtocolPreset } from "../types";
import { byId, el } from "./dom";
import { OdourSelect, type OdourOption } from "./odourSelect";
import { ProtocolPicker } from "./protocolPicker";

/** Status line while an experiment runs, e.g. "running: presentation 4 of 10 (40%) · 6 s". */
export function describeProgress(e: Pick<ExperimentSummary, "status" | "progress">, elapsedS: number): string {
  const clock = `${Math.round(elapsedS)} s`;
  if (e.status === "queued") return `queued (waiting for a free worker) · ${clock}`;
  if (e.status === "running" && e.progress && e.progress.total > 0) {
    const { done, total } = e.progress;
    const current = Math.min(done + 1, total);
    return `running: presentation ${current} of ${total} (${Math.round((100 * done) / total)}%) · ${clock}`;
  }
  return `${e.status} · ${clock}`;
}

/** Ready-made odour pairs (real odours). Similarities: correlation of DoOR receptor responses. */
export const ODOUR_PAIRS = [
  { label: "Classic pair", plus: "3-octanol", minus: "4-methylcyclohexanol",
    note: "the pair used in most fly learning experiments since Tully & Quinn (1985)" },
  { label: "Similar pair", plus: "3-octanol", minus: "1-octen-3-ol",
    note: "two mushroom-smelling alcohols with almost the same receptor pattern: hard to tell apart" },
  { label: "Very different", plus: "hexanoic acid", minus: "pyrrolidine",
    note: "an acid and an amine-like ring with opposite receptor patterns" },
];

/** Random-pattern odours: names are just labels. */
const RANDOM_ODOURS = ["odour_A", "odour_B", "odour_C", "odour_D", "odour_E", "odour_F"];

/** Plain words for a receptor-pattern correlation. */
export function describeSimilarity(r: number | null): string {
  if (r === null) return "Similarity unknown (too few receptors measured for both).";
  const words = r >= 0.8 ? "very similar: hard to tell apart"
    : r >= 0.5 ? "similar"
    : r >= 0.2 ? "somewhat different"
    : "very different: easy to tell apart";
  return `Receptor patterns ${words} (correlation ${r.toFixed(2).replace("-", "−")}).`;
}

export interface FormOptions {
  odoursAvailable: boolean;
  presets: ProtocolPreset[];          // empty: only the classic protocol
  lesionOptions: LesionOptions;
  defaultGain?: number;               // the server's graded_gain (e.g. calibrated); slider start
  catalog: OdourCatalogItem[];        // real odours for the menus (empty: none loaded)
  similarity?: (a: string, b: string) => Promise<number | null>;
  onSubmit: (req: ConditioningRequest) => void;
}

const DEFAULTS = {
  door: { plus: "3-octanol", minus: "4-methylcyclohexanol", c: "pentyl acetate" },
  random: { plus: "odour_A", minus: "odour_B", c: "odour_C" },
};

export class ExperimentForm {
  private readonly csPlus: OdourSelect;
  private readonly csMinus: OdourSelect;
  private readonly csC: OdourSelect;
  private readonly source = byId("odour-source", HTMLSelectElement);
  private readonly trials = byId("trials", HTMLInputElement);
  private readonly us = byId("us", HTMLSelectElement);
  private readonly aplGain = byId("apl-gain", HTMLInputElement);
  private readonly aplGainValue = byId("apl-gain-value", HTMLOutputElement);
  private readonly seed = byId("seed", HTMLInputElement);
  private readonly submit = byId("run-button", HTMLButtonElement);
  private readonly status = byId("form-status", HTMLParagraphElement);
  private readonly similarity = document.getElementById("odour-similarity");
  private readonly pairs = document.getElementById("odour-pairs");
  private readonly protocol: ProtocolPicker;
  private readonly real: OdourOption[];
  private gainTouched = false;        // only a moved slider overrides the server's default
  private similarityTicket = 0;

  constructor(
    private readonly form: HTMLFormElement,
    private readonly opts: FormOptions,
  ) {
    this.protocol = new ProtocolPicker(opts.presets, opts.lesionOptions, () => this.setStatus(""));
    this.real = opts.catalog.map((o) => ({ name: o.name, group: o.chemical_class, coverage: o.coverage }));
    const options = () => (this.source.value === "random"
      ? RANDOM_ODOURS.map((name) => ({ name, group: "random patterns", coverage: null }))
      : this.real);
    this.csPlus = new OdourSelect(byId("cs-plus", HTMLInputElement), options);
    this.csMinus = new OdourSelect(byId("cs-minus", HTMLInputElement), options);
    this.csC = new OdourSelect(this.protocol.csC, options);
    for (const s of [this.csPlus, this.csMinus]) s.input.addEventListener("change", () => this.showSimilarity());

    const doorOption = [...this.source.options].find((o) => o.value === "door");
    if (!opts.odoursAvailable && doorOption) {
      doorOption.disabled = true;
      this.source.value = "random";
      this.applyDefaults();
    }
    this.source.addEventListener("change", () => this.applyDefaults());
    this.renderPairs();

    if (opts.defaultGain !== undefined) this.aplGain.value = String(opts.defaultGain);
    this.aplGain.addEventListener("input", () => {
      this.gainTouched = true;
      this.showGain();
    });
    this.showGain();
    this.showSimilarity();
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const result = this.read();
      if (typeof result === "string") this.setStatus(result, "error");
      else this.opts.onSubmit(result);
    });
  }

  /** The request, or an error message if the inputs are invalid. */
  read(): ConditioningRequest | string {
    const plus = this.csPlus.value;
    const minus = this.csMinus.value;
    if (!plus || !minus) return "Choose both odours.";
    if (plus.toLowerCase() === minus.toLowerCase()) return "CS+ and CS− must be different odours.";
    const trials = Number(this.trials.value);
    if (!Number.isInteger(trials) || trials < 0 || trials > 20) return "Trials must be a whole number from 0 to 20.";
    const seed = Number(this.seed.value);
    if (!Number.isInteger(seed) || seed < 0) return "Seed must be a whole number ≥ 0.";
    const choice = this.protocol.choice();
    if (typeof choice === "string") return choice;
    const extra: ConditioningRequest["extra_odours"] = {};
    if (choice.needsC) {
      const c = this.csC.value;
      if (!c) return "Choose odour C.";
      if ([plus, minus].some((o) => o.toLowerCase() === c.toLowerCase())) {
        return "Odour C must differ from CS+ and CS−.";
      }
      extra.C = c;
    }
    return {
      cs_plus: plus,
      cs_minus: minus,
      odour_source: this.source.value === "random" ? "random" : "door",
      trials,
      us: this.us.value === "reward" ? "reward" : "shock",
      seed,
      params: { ...choice.params, ...(this.gainTouched ? { graded_gain: Number(this.aplGain.value) } : {}) },
      steps: choice.steps,
      ...(choice.steps && choice.readout ? { readout: choice.readout } : {}),
      extra_odours: extra,
      lesions: this.protocol.selectedLesions(),
    };
  }

  setBusy(busy: boolean): void {
    this.submit.disabled = busy;
    this.submit.textContent = busy ? "Running…" : "Run experiment";
  }

  setStatus(text: string, kind: "info" | "error" = "info"): void {
    this.status.textContent = text;
    this.status.className = `status ${kind}`;
  }

  /** Buttons that fill in a ready-made pair (real odours only, and only pairs DoOR has). */
  private renderPairs(): void {
    if (!this.pairs) return;
    const known = new Set(this.real.map((o) => o.name));
    const usable = this.source.value === "door" ? ODOUR_PAIRS.filter((p) => known.has(p.plus) && known.has(p.minus)) : [];
    this.pairs.replaceChildren(...usable.map((p) => {
      const b = el("button", { class: "chip", text: p.label, title: `${p.plus} vs ${p.minus}: ${p.note}` });
      b.type = "button";
      b.addEventListener("click", () => {
        this.csPlus.value = p.plus;
        this.csMinus.value = p.minus;
        this.showSimilarity();
      });
      return b;
    }));
    this.pairs.hidden = !usable.length;
  }

  /** "Receptor patterns similar (0.62)" under the odours, from the server. */
  private showSimilarity(): void {
    if (!this.similarity) return;
    const a = this.csPlus.value, b = this.csMinus.value;
    const ticket = ++this.similarityTicket;
    const known = (n: string) => this.real.some((o) => o.name === n);
    if (this.source.value !== "door" || !this.opts.similarity || !known(a) || !known(b) || a === b) {
      this.similarity.textContent = "";
      return;
    }
    this.opts.similarity(a, b).then((r) => {
      if (ticket === this.similarityTicket && this.similarity) this.similarity.textContent = describeSimilarity(r);
    }).catch(() => undefined);              // a hint only
  }

  private applyDefaults(): void {
    const d = this.source.value === "random" ? DEFAULTS.random : DEFAULTS.door;
    this.csPlus.value = d.plus;
    this.csMinus.value = d.minus;
    this.csC.value = d.c;
    this.renderPairs();
    this.showSimilarity();
  }

  private showGain(): void {
    const g = Number(this.aplGain.value);
    this.aplGainValue.value = g === 0 ? "off" : Number(g.toPrecision(2)).toString();
  }
}
