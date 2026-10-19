// legend.ts — neuron groups with colors, counts and visibility toggles.

import { cssColor, groupColor } from "../colors";
import { el } from "./dom";

export const GROUP_LABELS: Record<string, string> = {
  ORN: "olfactory receptor neurons",
  ALLN: "antennal lobe local neurons",
  ALPN: "projection neurons",
  KC: "Kenyon cells",
  APL: "APL (inhibition)",
  DPM: "DPM",
  MBON: "output neurons",
  DAN_PPL1: "dopamine: punishment",
  DAN_PAM: "dopamine: reward",
};

/** Signal-flow order; unknown groups go last, alphabetically. */
const ORDER = ["ORN", "ALLN", "ALPN", "KC", "APL", "DPM", "MBON", "DAN_PPL1", "DAN_PAM"];

export function orderGroups(groups: string[]): string[] {
  const rank = (g: string) => (ORDER.includes(g) ? ORDER.indexOf(g) : ORDER.length);
  return [...groups].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** One row per group: a visibility checkbox, its color, its name and size. With
 *  `onFocus`, the name is a button that shows what the group connects to. */
export function renderLegend(
  root: HTMLElement,
  counts: Record<string, number>,
  onToggle: (group: string, visible: boolean) => void,
  onFocus?: (group: string) => void,
): void {
  const items = orderGroups(Object.keys(counts)).map((g) => {
    const box = el("input");
    box.type = "checkbox";
    box.checked = true;
    box.setAttribute("aria-label", `show ${GROUP_LABELS[g] ?? g}`);
    box.addEventListener("change", () => onToggle(g, box.checked));
    const swatch = el("span", { class: "swatch" });
    swatch.style.background = cssColor(groupColor(g));
    let name: HTMLElement;
    if (onFocus) {
      name = el("button", { class: "legend-name link-button", text: GROUP_LABELS[g] ?? g,
                            title: `${g}: show what it connects to` });
      (name as HTMLButtonElement).type = "button";
      name.addEventListener("click", () => onFocus(g));
    } else {
      name = el("span", { class: "legend-name", text: GROUP_LABELS[g] ?? g, title: g });
    }
    return el("div", { class: "legend-item" }, [
      box,
      swatch,
      name,
      el("span", { class: "legend-count", text: String(counts[g]) }),
    ]);
  });
  root.replaceChildren(...items);
}

export interface DisplayOption {
  label: string;
  title: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}

/** Checkboxes for what the 3D view draws (brain regions, labels, neuron shapes). */
export function renderDisplayOptions(root: HTMLElement, options: DisplayOption[]): void {
  root.replaceChildren(...options.map((o) => {
    const box = el("input");
    box.type = "checkbox";
    box.checked = o.checked;
    box.addEventListener("change", () => o.onChange(box.checked));
    return el("label", { class: "check", title: o.title }, [box, ` ${o.label}`]);
  }));
}
