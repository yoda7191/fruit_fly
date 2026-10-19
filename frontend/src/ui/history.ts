// history.ts — the "previous experiments" picker.

import type { ExperimentSummary } from "../types";

export function describeExperiment(e: ExperimentSummary): string {
  const time = new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const r = e.request;
  const silenced = (r.lesions ?? []).map((l) => l.group ?? l.cell_type).filter(Boolean).join(", ");
  return `${time} \u00b7 ${r.cs_plus} vs ${r.cs_minus} \u00b7 ${r.us}, ${r.trials} trials` +
         `${silenced ? ` \u00b7 ${silenced} silenced` : ""} \u00b7 ${e.status}`;
}

export function renderHistory(select: HTMLSelectElement, experiments: ExperimentSummary[],
                              selectedId: string | null): void {
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = experiments.length ? "Previous experiments\u2026" : "No previous experiments";
  const options = experiments.map((e) => {
    const o = document.createElement("option");
    o.value = e.id;
    o.textContent = describeExperiment(e);
    o.disabled = e.status !== "done";
    return o;
  });
  select.replaceChildren(placeholder, ...options);
  select.value = selectedId && experiments.some((e) => e.id === selectedId) ? selectedId : "";
}