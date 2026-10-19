// protocolPicker.ts — choosing a protocol (preset or edited JSON) and lesions.

import type { Lesion, LesionOptions, ParamOverrides, ProtocolPreset, ProtocolStep, Readout } from "../types";
import { byId, el } from "./dom";
import { GROUP_LABELS, orderGroups } from "./legend";

export const CLASSIC = "differential";

export interface ProtocolChoice {
  steps: ProtocolStep[] | null;      // null: the classic protocol, built from `trials`
  readout?: Readout;
  params: ParamOverrides;
  needsC: boolean;
}

/** The editable JSON view of a protocol: {"steps": [...], "readout": {...}}. */
export function protocolText(p: Pick<ProtocolPreset, "steps" | "readout">): string {
  const steps = p.steps.map((s) => {
    // keep the JSON short: drop fields that are at their defaults
    const out: Record<string, unknown> = { phase: s.phase };
    if (s.odour) out.odour = s.odour;
    if (s.us && s.us !== "none") out.us = s.us;
    if (s.us_onset_ms) out.us_onset_ms = s.us_onset_ms;
    for (const k of ["odour_ms", "us_ms", "gap_ms"] as const) if (s[k] !== null && s[k] !== undefined) out[k] = s[k];
    if (s.repeat && s.repeat !== 1) out.repeat = s.repeat;
    return out;
  });
  return JSON.stringify({ steps, readout: p.readout }, null, 1).replace(/\n {2,}/g, " ").replace(/\n }/g, " }");
}

/** Parse the JSON view; returns an error message instead of throwing. The
 *  server validates fully; this only catches what would confuse the user. */
export function parseProtocolText(text: string): { steps: ProtocolStep[]; readout?: Readout } | string {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return `Protocol JSON: ${(e as Error).message}`;
  }
  const obj = data as { steps?: unknown; readout?: unknown };
  if (typeof obj !== "object" || obj === null || !Array.isArray(obj.steps)) {
    return 'Protocol JSON must be an object with a "steps" list.';
  }
  if (obj.steps.length === 0) return "The protocol needs at least one step.";
  for (const [i, s] of obj.steps.entries()) {
    if (typeof s !== "object" || s === null || typeof (s as ProtocolStep).phase !== "string") {
      return `Step ${i + 1} needs a "phase".`;
    }
  }
  return { steps: obj.steps as ProtocolStep[], readout: obj.readout as Readout | undefined };
}

/** Lesion menu values: "group:APL" / "type:MBON01". */
export function encodeLesion(l: Lesion): string {
  return l.group !== undefined ? `group:${l.group}` : `type:${l.cell_type}`;
}

export function decodeLesion(value: string): Lesion {
  const [kind, ...rest] = value.split(":");
  const name = rest.join(":");
  return kind === "group" ? { group: name } : { cell_type: name };
}

export class ProtocolPicker {
  private readonly select = byId("protocol", HTMLSelectElement);
  private readonly info = byId("protocol-info", HTMLDivElement);
  private readonly cLabel = byId("cs-c-label", HTMLElement);
  readonly csC = byId("cs-c", HTMLInputElement);
  private readonly json = byId("protocol-json", HTMLTextAreaElement);
  private readonly lesions = byId("lesions", HTMLElement);
  private readonly lesionBoxes: HTMLInputElement[] = [];
  private readonly presets: Map<string, ProtocolPreset>;
  private edited = false;

  constructor(presets: ProtocolPreset[], lesionOptions: LesionOptions, private readonly onChange: () => void) {
    this.presets = new Map(presets.map((p) => [p.name, p]));
    const options = presets.length
      ? presets.map((p) => { const o = el("option", { text: p.title }); o.value = p.name; return o; })
      : [Object.assign(el("option", { text: "Differential conditioning" }), { value: CLASSIC })];
    this.select.replaceChildren(...options);
    this.select.value = this.presets.has(CLASSIC) || !presets.length ? CLASSIC : presets[0]!.name;
    this.select.addEventListener("change", () => this.show());
    this.json.addEventListener("input", () => { this.edited = true; });

    this.buildLesions(lesionOptions);
    this.show();
  }

  get name(): string {
    return this.select.value;
  }

  /** The chosen protocol, or an error message. */
  choice(): ProtocolChoice | string {
    const preset = this.presets.get(this.name);
    if (this.name === CLASSIC && !this.edited) {
      return { steps: null, params: preset?.params ?? {}, needsC: false };
    }
    const parsed = parseProtocolText(this.json.value);
    if (typeof parsed === "string") return parsed;
    return {
      steps: parsed.steps,
      readout: parsed.readout,
      params: preset?.params ?? {},
      needsC: parsed.steps.some((s) => s.odour?.split("+").includes("C")) || parsed.readout?.plus === "C" ||
              parsed.readout?.minus === "C",
    };
  }

  selectedLesions(): Lesion[] {
    return this.lesionBoxes.filter((b) => b.checked).map((b) => decodeLesion(b.value));
  }

  /** A checkbox per group and per cell type, a filter, and a summary of what's silenced. */
  private buildLesions(options: LesionOptions): void {
    const summary = el("p", { class: "lesion-summary muted small" });
    const update = () => {
      const n = this.lesionBoxes.filter((b) => b.checked).length;
      summary.textContent = n ? `${n} silenced` : "none silenced: the intact fly";
      this.onChange();
    };
    const box = (value: string, label: string, title: string) => {
      const input = el("input");
      input.type = "checkbox";
      input.value = value;
      input.addEventListener("change", update);
      this.lesionBoxes.push(input);
      return el("label", { class: "check", title }, [input, ` ${label}`]);
    };
    const groups = orderGroups(options.groups).map((g) =>
      box(encodeLesion({ group: g }), GROUP_LABELS[g] ?? g, `every neuron of group ${g}`));
    const types = options.cell_types.map((t) => box(encodeLesion({ cell_type: t }), t, `cell type ${t}`));
    const filter = el("input");
    filter.type = "search";
    filter.placeholder = "filter cell types, e.g. MBON01, PPL1";
    filter.setAttribute("aria-label", "filter cell types");
    const typeList = el("div", { class: "check-list" }, types);
    filter.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      for (const t of types) t.hidden = !!q && !t.textContent!.toLowerCase().includes(q);
    });
    this.lesions.replaceChildren(
      el("div", { class: "check-grid" }, groups),
      ...(types.length ? [el("details", { class: "cell-types" }, [
        el("summary", { text: `Single cell types (${types.length})` }), filter, typeList])] : []),
      summary,
    );
    summary.textContent = "none silenced: the intact fly";
  }

  private show(): void {
    const p = this.presets.get(this.name);
    this.edited = false;
    if (!p) {
      this.info.replaceChildren();
      this.json.value = "";
      this.cLabel.hidden = true;
      this.onChange();
      return;
    }
    this.info.replaceChildren(
      el("p", { text: p.description }),
      el("p", { class: "muted small" }, [el("strong", { text: "In flies: " }), p.in_flies]),
      el("p", { class: "muted small" }, [el("strong", { text: "In this model: " }), p.in_model]),
    );
    this.json.value = protocolText(p);
    this.cLabel.hidden = !p.extra_odour_slots.includes("C");
    this.onChange();
  }
}