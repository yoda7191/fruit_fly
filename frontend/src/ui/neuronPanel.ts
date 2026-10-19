// neuronPanel.ts — details of the neuron clicked in the 3D view: identity, its largest
// input and output partners, and (with an experiment loaded) its firing per presentation.

import { cssColor, ROLE_COLORS } from "../colors";
import type { GroupConnection, NeuronActivity, NeuronConnections, NeuronDetail, Partner } from "../types";
import { el } from "./dom";
import { GROUP_LABELS } from "./legend";

const REGION: Record<string, string> = {
  CA: "calyx", PED: "peduncle", VL: "vertical lobe", ML: "medial lobe",
};

const TRANSMITTER: Record<string, string> = {
  ACH: "acetylcholine", GABA: "GABA", GLUT: "glutamate", DA: "dopamine", SER: "serotonin", OCT: "octopamine",
};

function partnerList(title: string, total: number, partners: Partner[]): HTMLElement {
  if (!partners.length) return el("p", { class: "muted small", text: `${title}: none in the model` });
  const shown = partners.reduce((s, p) => s + p.synapses, 0);
  return el("div", { class: "partners" }, [
    el("h4", { text: `${title} · ${total.toLocaleString()} synapses` }),
    el("ul", {}, partners.map((p) => el("li", { class: `partner ${p.sign}`, title: p.sign }, [
      el("span", { class: "partner-type", text: p.cell_type }),
      el("span", { class: "muted small", text: ` ${GROUP_LABELS[p.group] ?? p.group} · ${p.neurons} ` +
                                              `${p.neurons === 1 ? "neuron" : "neurons"}` }),
      el("span", { class: "partner-syn", text: p.synapses.toLocaleString() }),
    ]))),
    shown < total ? el("p", { class: "muted small", text: `+ ${(total - shown).toLocaleString()} more` }) : null,
  ]);
}

/** "168", "3.5", "0": whole hertz once it's large, one decimal below 10. */
export function rate(hz: number): string {
  return hz >= 10 ? hz.toFixed(0) : hz === 0 ? "0" : hz.toFixed(1);
}

/** Firing rate per presentation as bars, the US marked. */
export function activityBars(activity: NeuronActivity): HTMLElement {
  const max = Math.max(1, ...activity.presentations.map((p) => p.rate_hz));
  return el("div", { class: "activity" }, [
    el("h4", { text: `Firing in this experiment · ${activity.total_spikes.toLocaleString()} spikes` }),
    ...activity.presentations.map((p) => el("div", { class: "activity-row", title: `${p.phase}: ${p.label}` }, [
      el("span", { class: "activity-label", text: `${p.label}${p.us !== "none" ? ` + ${p.us}` : ""}` }),
      el("span", { class: "bar" }, [el("span", { class: `bar-fill${p.us !== "none" ? " us" : ""}`,
                                                  style: `width:${(100 * p.rate_hz) / max}%` })]),
      el("span", { class: "activity-rate", text: `${rate(p.rate_hz)} Hz` }),
    ])),
  ]);
}

export interface PanelOptions {
  codexLinks: boolean;            // real FlyWire ids: link to the cell in FlyWire Codex
  onClose: () => void;
  extra?: HTMLElement | null;     // shown under the identity line (the connection controls)
}

/** Colored dots naming the roles drawn in 3D. */
export function roleKey(roles: (keyof typeof ROLE_COLORS)[]): HTMLElement {
  const words: Record<keyof typeof ROLE_COLORS, string> = {
    selected: "selected", input: "sends to it", output: "receives from it", both: "both ways",
    dopamine: "dopamine",
  };
  return el("p", { class: "role-key-row small" }, roles.map((r) => el("span", { class: "role" }, [
    el("span", { class: "dot", style: `background:${cssColor(ROLE_COLORS[r])}` }), ` ${words[r]}`,
  ])));
}

/**
 * The connection explorer's controls: how many partners are drawn, and a slider for
 * the fewest synapses a drawn connection has.
 */
export function connectionControls(c: NeuronConnections | "loading", minSynapses: number, maxDrawn: number,
                                   onMinSynapses: (n: number) => void): HTMLElement {
  const slider = el("input");
  slider.type = "range";
  slider.min = "1";
  slider.max = "30";
  slider.step = "1";
  slider.value = String(minSynapses);
  slider.setAttribute("aria-label", "fewest synapses per drawn connection");
  const value = el("output", { text: String(minSynapses) });
  slider.addEventListener("input", () => { value.textContent = slider.value; });
  slider.addEventListener("change", () => onMinSynapses(Number(slider.value)));
  const drawn = (shown: number, total: number) =>
    total > shown ? `strongest ${shown} of ${total.toLocaleString()}` : `${total.toLocaleString()}`;
  const summary = c === "loading" ? "Loading connections\u2026"
    : `Drawn in 3D: ${drawn(Math.min(maxDrawn, c.inputs.length), c.total_inputs)} input` +
      `${c.total_inputs === 1 ? "" : "s"}, ${drawn(Math.min(maxDrawn, c.outputs.length), c.total_outputs)} output` +
      `${c.total_outputs === 1 ? "" : "s"}` +
      (c.dopamine_to.length ? `, dopamine to ${c.dopamine_to.length} output neurons` : "") +
      (c.dopamine_from.length ? `, dopamine from ${c.dopamine_from.length} DANs` : "");
  return el("div", { class: "explorer" }, [
    el("h4", { text: "Connections" }),
    el("p", { class: "small", text: summary }),
    el("label", { class: "small inline-range" }, ["at least ", value, " synapses ", slider]),
    roleKey(["input", "output", "both", "dopamine"]),
  ]);
}

function groupRows(title: string, rows: GroupConnection[], other: (r: GroupConnection) => string): HTMLElement {
  if (!rows.length) return el("p", { class: "muted small", text: `${title}: none in the model` });
  return el("div", { class: "partners" }, [
    el("h4", { text: title }),
    el("ul", {}, rows.map((r) => {
      const amount = r.sign === "dopamine" ? `${r.connections.toLocaleString()} pairs`
        : `${r.synapses.toLocaleString()} syn.`;
      return el("li", { class: `partner ${r.sign}`, title: `${r.sign}; ${r.connections.toLocaleString()} connected pairs` }, [
        el("span", { class: "partner-type", text: GROUP_LABELS[other(r)] ?? other(r) }),
        el("span", { class: "muted small", text: r.sign === "dopamine" ? " dopamine" : "" }),
        el("span", { class: "partner-syn", text: amount }),
      ]);
    })),
  ]);
}

/** A neuron group: its size and the groups it connects to (both directions). */
export function renderGroup(root: HTMLElement, group: string, count: number,
                            partners: { inputs: GroupConnection[]; outputs: GroupConnection[] },
                            onClose: () => void): void {
  const close = el("button", { class: "close", text: "×", title: "close" });
  close.type = "button";
  close.addEventListener("click", onClose);
  root.replaceChildren(
    el("div", { class: "neuron-head" }, [el("h3", { text: GROUP_LABELS[group] ?? group }), close]),
    el("p", { class: "muted small", text: `${group} \u00b7 ${count.toLocaleString()} neurons \u00b7 ` +
                                         "tubes join the groups' centres in each hemisphere" }),
    roleKey(["input", "output", "both", "dopamine"]),
    groupRows("Inputs from", partners.inputs, (r) => r.pre),
    groupRows("Outputs to", partners.outputs, (r) => r.post),
  );
  root.hidden = false;
}

export function renderNeuron(root: HTMLElement, d: NeuronDetail, activity: NeuronActivity | null | "loading",
                             opts: PanelOptions): void {
  const close = el("button", { class: "close", text: "×", title: "close" });
  close.type = "button";
  close.addEventListener("click", opts.onClose);
  const transmitter = d.transmitter ? (TRANSMITTER[d.transmitter] ?? d.transmitter) : "unknown transmitter";
  const id = opts.codexLinks
    ? Object.assign(el("a", { text: `FlyWire ${d.flywire_id}` }),
                    { href: `https://codex.flywire.ai/app/cell_details?root_id=${encodeURIComponent(d.flywire_id)}`,
                      target: "_blank", rel: "noopener noreferrer" })
    : el("span", { text: `id ${d.root_id}` });
  root.replaceChildren(
    el("div", { class: "neuron-head" }, [
      el("h3", { text: d.cell_type || d.group }),
      close,
    ]),
    el("p", { class: "muted small" }, [
      `${GROUP_LABELS[d.group] ?? d.group} · ${transmitter}${d.graded ? " · non-spiking" : ""}` +
      `${d.region ? ` · ${REGION[d.region] ?? d.region} part` : ""}` +
      `${d.side ? ` · ${d.side}` : ""} · `, id,
    ]),
    ...(opts.extra ? [opts.extra] : []),
    partnerList("Inputs", d.input_synapses, d.inputs),
    partnerList("Outputs", d.output_synapses, d.outputs),
    activity === "loading" ? el("p", { class: "muted small", text: "Loading activity…" })
      : activity ? activityBars(activity)
      : el("p", { class: "muted small", text: "Run or open an experiment to see this neuron's firing." }),
  );
  root.hidden = false;
}
