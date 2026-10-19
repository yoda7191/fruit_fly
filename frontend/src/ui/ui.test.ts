import { describe, expect, it, vi } from "vitest";

import type { ExperimentDetail, ExperimentResult, ExperimentSummary, ProtocolPreset, SweepDetail, TimelineEntry } from "../types";
import { formatNumber, formatPercent } from "./dom";
import { orderGroups, renderLegend } from "./legend";
import { describePI, interpret, noPredictionReason, protocolLines, renderResults } from "./results";
import { decodeLesion, encodeLesion, parseProtocolText, protocolText, ProtocolPicker } from "./protocolPicker";
import { extent, renderSweep, renderSweepChart, valueLabel } from "./sweepChart";
import { lesionExample, parseLesionValues, parseValues, SweepPanel, sweepOutcome } from "./sweepPanel";
import { describeProgress, ExperimentForm } from "./experimentForm";
import { loadKey, saveKey, setupApiKey } from "./apiKey";
import { ApiClient } from "../api";
import { describeEntry, entryAt, Timeline, trainingEnd } from "./timeline";

describe("formatting", () => {
  it("formats percentages and numbers", () => {
    expect(formatPercent(0.12)).toBe("+12%");
    expect(formatPercent(-0.625)).toBe("\u221262%");
    expect(formatPercent(0.001)).toBe("0%");
    expect(formatPercent(0.5, false)).toBe("50%");
    expect(formatPercent(null)).toBe("\u2014");
    expect(formatNumber(-0.123)).toBe("\u22120.12");
    expect(formatNumber(Number.NaN)).toBe("\u2014");
  });
});

describe("interpret", () => {
  it("classifies learning outcomes", () => {
    expect(interpret({ valid: false, cs_plus: null, cs_minus: null }).verdict).toBe("none");
    expect(interpret({ valid: true, cs_plus: -0.05, cs_minus: 0 }).verdict).toBe("weak");
    expect(interpret({ valid: true, cs_plus: -0.65, cs_minus: -0.41 }).verdict).toBe("generalized");
    expect(interpret({ valid: true, cs_plus: -0.84, cs_minus: 0.02 }).verdict).toBe("specific");
  });
});

const entries: TimelineEntry[] = [
  { label: "A", slot: "A", us: "none", phase: "pre", t_start_ms: 0, t_end_ms: 1000, us_start_ms: null, us_end_ms: null },
  { label: "A", slot: "A", us: "shock", phase: "training", t_start_ms: 3000, t_end_ms: 4000,
    us_start_ms: 3000, us_end_ms: 4000 },
];

describe("timeline", () => {
  it("finds the entry under the playhead", () => {
    expect(entryAt(entries, 500)?.phase).toBe("pre");
    expect(entryAt(entries, 1000)).toBeNull();          // end is exclusive
    expect(describeEntry(entryAt(entries, 3500))).toBe("training \u00b7 A + shock");
    expect(describeEntry(null)).toBe("rest");
  });

  it("renders blocks, updates the clock, and seeks on click", () => {
    const root = document.createElement("div");
    const onSeek = vi.fn();
    const t = new Timeline(root, { onSeek, onToggle: vi.fn(), onSpeed: vi.fn() });
    t.setExperiment(entries, 10_000);
    const blocks = root.querySelectorAll<HTMLElement>(".block");
    expect(blocks).toHaveLength(2);
    expect(blocks[1]!.style.left).toBe("30%");
    expect(blocks[1]!.classList.contains("us-shock")).toBe(true);
    t.setTime(3500, { playing: true, buffering: false });
    expect(root.querySelector(".clock")!.textContent).toBe("3.5 s / 10.0 s");
    expect(root.querySelector(".phase")!.textContent).toContain("shock");

    const track = root.querySelector<HTMLElement>(".track")!;
    track.getBoundingClientRect = () => ({ left: 100, width: 200 } as DOMRect);
    track.dispatchEvent(new MouseEvent("click", { clientX: 150 }));
    expect(onSeek).toHaveBeenCalledWith(2500);
  });
});

describe("progress and training end", () => {
  it("describes experiment progress", () => {
    expect(describeProgress({ status: "queued", progress: null }, 1.4)).toBe("queued (waiting for a free worker) \u00b7 1 s");
    expect(describeProgress({ status: "running", progress: { done: 3, total: 10 } }, 6))
      .toBe("running: presentation 4 of 10 (30%) \u00b7 6 s");
    expect(describeProgress({ status: "running", progress: { done: 10, total: 10 } }, 9))
      .toContain("presentation 10 of 10 (100%)");
    expect(describeProgress({ status: "running", progress: null }, 0)).toBe("running \u00b7 0 s");
  });

  it("finds when training ends", () => {
    expect(trainingEnd(entries)).toBe(4000);
    expect(trainingEnd(entries.filter((e) => e.phase !== "training"))).toBeNull();
  });
});

describe("legend", () => {
  it("orders groups along the signal path and toggles visibility", () => {
    expect(orderGroups(["MBON", "ZZZ", "ORN", "KC"])).toEqual(["ORN", "KC", "MBON", "ZZZ"]);
    expect(orderGroups(["ALPN", "ALLN", "ORN"])).toEqual(["ORN", "ALLN", "ALPN"]);
    const root = document.body.appendChild(document.createElement("div"));  // events need a connected node
    const onToggle = vi.fn();
    renderLegend(root, { KC: 1000, ORN: 980 }, onToggle);
    const boxes = root.querySelectorAll<HTMLInputElement>("input[type=checkbox]");
    expect(root.querySelector(".legend-count")!.textContent).toBe("980");   // ORN first
    boxes[1]!.click();
    expect(onToggle).toHaveBeenCalledWith("KC", false);
    root.remove();
  });
});

let lastDetail: ExperimentDetail | null = null;

describe("renderResults", () => {
  it("shows the outcome and never interprets names as HTML", () => {
    const evil = "<img src=x onerror=alert(1)>";
    const detail = {
      id: "1", sweep_id: null, status: "done", progress: { done: 6, total: 6 },
      created_at: "", started_at: null, finished_at: null, error: null,
      request: { cs_plus: evil, cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 1,
                 params: {}, protocol: { stim_ms: 1000, gap_ms: 2000, settle_ms: 500, us_hz: 40 },
                 behavior: { sharpness: 6, flies: 100 },
                 steps: null, extra_odours: {}, readout: { plus: "A", minus: "B", before: "pre", after: "post" }, lesions: [] },
      result: {
        readout: { plus: "A", minus: "B", before: "pre", after: "post" }, readout_after_ms: 20000, odours: { A: evil, B: "B" }, lesioned: [],
        separation: { pn_correlation: 0.4, kc_correlation: null, kc_active_plus: 0.05,
                      kc_active_minus: 0.06, kc_shared: 3 },
        mbons: [{ cell_type: "MBON01", n: 2, us_target: true, pre_plus: 30, post_plus: 5,
                  pre_minus: 28, post_minus: 29 }],
        compartment_change: { valid: true, cs_plus: -0.83, cs_minus: 0.04 },
        mean_weight_ratio: 0.99, mbon_weights: [], timeline: [], duration_ms: 30500,
        n_spikes: 1234, coverage: null, input_similarity: null,
        behavior: {
          valid: true, valenced_mbons: 20,
          naive: { drive_plus: -0.11, drive_minus: -0.02, p_plus: 0.37, preference: -0.26 },
          trained: { drive_plus: -0.62, drive_minus: -0.03, p_plus: 0.03, preference: -0.94 },
          learned_drive: -0.5, performance_index: 0.91, flies: 100, sampled_performance_index: 0.98,
        },
      },
    } as ExperimentDetail;
    lastDetail = detail;
    const root = document.createElement("div");
    renderResults(root, detail);
    expect(root.querySelector("img")).toBeNull();
    expect(root.textContent).toContain(evil);
    expect(root.querySelector(".verdict")!.classList.contains("specific")).toBe(true);
    expect(root.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(root.textContent).toContain("\u221283%");
    // T-maze section
    expect(root.querySelector(".pi-value")!.textContent).toBe("0.91");
    expect(root.querySelector(".pi-label")!.textContent).toContain("strong learning");
    expect(root.querySelector(".arm.plus")!.textContent).toBe("CS+ 3%");
    expect(root.querySelector(".arm.minus")!.textContent).toBe("CS\u2212 97%");
    expect(root.textContent).toContain("\u22120.11 \u2192 \u22120.62");
  });
  it("explains when no T-maze prediction is possible instead of showing a number", () => {
    expect(noPredictionReason({ valenced_mbons: 0 })).toContain("known transmitter");
    expect(noPredictionReason({ valenced_mbons: 4 })).toContain("didn't fire");
    const detail = JSON.parse(JSON.stringify(lastDetail!)) as ExperimentDetail;
    detail.result!.behavior = { ...detail.result!.behavior, valid: false, valenced_mbons: 0,
                                learned_drive: null, performance_index: null, sampled_performance_index: null };
    const root = document.createElement("div");
    renderResults(root, detail);
    expect(root.querySelector(".pi-value")).toBeNull();
    expect(root.textContent).toContain("No prediction");
    expect(root.textContent).not.toContain("no clear learning");
  });

  it("describes performance indices", () => {
    expect(describePI(0.05)).toBe("no clear learning");
    expect(describePI(0.2)).toBe("weak learning");
    expect(describePI(0.45)).toBe("moderate learning");
    expect(describePI(0.9)).toBe("strong learning");
    expect(describePI(-0.5)).toBe("moderate learning in the wrong direction");
  });
});

describe("sweeps", () => {
  it("parses value lists", () => {
    expect(parseValues("0, 0.05;0.1  0.2")).toEqual([0, 0.05, 0.1, 0.2]);
    expect(parseValues("5e-7,1e-6")).toEqual([5e-7, 1e-6]);
    expect(parseValues("")).toBe("Enter at least one value.");
    expect(parseValues("1, x")).toBe('"x" is not a number.');
    expect(parseValues("1, 1")).toBe("1 appears twice.");
    expect(parseValues(Array.from({ length: 26 }, (_, i) => i).join(","))).toBe("At most 25 values.");
  });

  it("pads axis ranges and always includes zero", () => {
    const [lo, hi] = extent([0.2, 0.8]);
    expect(lo).toBeLessThan(0);
    expect(hi).toBeGreaterThan(0.8);
    expect(extent([])).toEqual([-1.16, 1.16]);
  });

  const stats = (mean: number | null, std: number | null, n: number) => ({ mean, std, n });
  const detail: SweepDetail = {
    id: "s1", created_at: "2026-01-01T00:00:00Z", parameter: "params.graded_gain",
    values: [0, 0.05, 0.1], repeats: 2, total: 6, status: "running",
    counts: { queued: 1, running: 1, done: 4, failed: 0, cancelled: 0 },
    base: { cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 3, us: "shock", seed: 1,
            params: {}, protocol: { stim_ms: 1000, gap_ms: 2000, settle_ms: 500, us_hz: 40 },
            behavior: { sharpness: 6, flies: 100 }, steps: null, extra_odours: {},
            readout: { plus: "A", minus: "B", before: "pre", after: "post" }, lesions: [] },
    metrics: ["performance_index", "kc_active_plus"],
    points: [
      { value: 0, done: 2, metrics: { performance_index: stats(0.2, 0.1, 2), kc_active_plus: stats(0.4, 0.02, 2) } },
      { value: 0.05, done: 2, metrics: { performance_index: stats(0.8, 0.05, 2), kc_active_plus: stats(0.05, 0.01, 2) } },
      { value: 0.1, done: 0, metrics: { performance_index: stats(null, null, 0), kc_active_plus: stats(null, null, 0) } },
    ],
  };

  it("draws a point per finished value with SD bars", () => {
    const chart = renderSweepChart(detail.points, "performance_index");
    expect(chart.querySelectorAll("circle.point")).toHaveLength(2);          // the third has no data yet
    expect(chart.querySelectorAll("line.error-bar")).toHaveLength(2 * 3);    // bar + two caps each
    expect(chart.querySelector("circle title")!.textContent).toContain("n = 2");
    const empty = renderSweepChart(detail.points.map((p) => ({ ...p, metrics: {} })), "performance_index");
    expect(empty.textContent).toContain("no finished experiments yet");
  });

  it("renders progress, a metric picker and a CSV link", () => {
    const root = document.body.appendChild(document.createElement("div"));
    const onMetric = vi.fn();
    renderSweep(root, detail, "kc_active_plus", "/api/sweeps/s1/results.csv", onMetric);
    expect(root.textContent).toContain("4 of 6 experiments finished");
    expect(root.querySelector("a")!.getAttribute("href")).toBe("/api/sweeps/s1/results.csv");
    const select = root.querySelector("select")!;
    expect(select.value).toBe("kc_active_plus");
    select.value = "performance_index";
    select.dispatchEvent(new Event("change"));
    expect(onMetric).toHaveBeenCalledWith("performance_index");
    root.remove();
  });
});

describe("lesion scans", () => {
  const options = { groups: ["APL", "DAN_PPL1", "KC"], cell_types: ["MBON01", "KCa'b' ap1"] };

  it("parses lesion labels and checks them against the circuit", () => {
    expect(parseLesionValues("none, group:APL; type:KCa'b' ap1", options))
      .toEqual(["none", "group:APL", "type:KCa'b' ap1"]);                 // spaces stay inside names
    expect(parseLesionValues("none, APL", options)).toContain("group:<group>");
    expect(parseLesionValues("group:APLL", options)).toContain('no group "APLL"');
    expect(parseLesionValues("type:MBON99", options)).toContain('no cell type "MBON99"');
    expect(parseLesionValues("none, none", options)).toContain("twice");
    expect(parseLesionValues(" ", options)).toContain("at least one");
    expect(parseLesionValues("group:ANYTHING")).toEqual(["group:ANYTHING"]);  // no options: format only
  });

  it("builds the example from groups the circuit has", () => {
    expect(lesionExample(options)).toBe("none, group:APL, group:DAN_PPL1");
    expect(lesionExample()).toBe("none, group:APL, group:DPM, group:DAN_PPL1, group:DAN_PAM");
  });

  it("reads a lesion scan request from the panel", () => {
    document.body.innerHTML = `<select id="sweep-parameter"></select><input id="sweep-values">
      <input id="sweep-repeats" value="2"><button id="sweep-button"></button><p id="sweep-status"></p>
      <select id="sweep-history"></select>`;
    const base = { cs_plus: "A", cs_minus: "B", odour_source: "random" as const, trials: 1, us: "shock" as const,
                   seed: 1 };
    const panel = new SweepPanel({ getBase: () => base, onSubmit: vi.fn(), onPick: vi.fn(), lesionOptions: options });
    const select = document.getElementById("sweep-parameter") as HTMLSelectElement;
    select.value = "lesion";
    select.dispatchEvent(new Event("change"));
    expect((document.getElementById("sweep-values") as HTMLInputElement).value).toBe(lesionExample(options));
    expect(panel.read()).toEqual({ base, parameter: "lesion", values: ["none", "group:APL", "group:DAN_PPL1"],
                                   repeats: 2 });
    document.body.innerHTML = "";
  });

  it("charts lesions as categories, without a connecting line", () => {
    const st = (mean: number) => ({ performance_index: { mean, std: 0.05, n: 2 } });
    const points = [{ value: "none", done: 2, metrics: st(0.6) }, { value: "group:DAN_PPL1", done: 2, metrics: st(0) },
                    { value: "type:MBON01", done: 2, metrics: st(0.5) }];
    const chart = renderSweepChart(points, "performance_index");
    expect(chart.querySelectorAll("circle.point")).toHaveLength(3);
    expect(chart.querySelector("path.mean-line")).toBeNull();
    const labels = [...chart.querySelectorAll("text.tick")].map((t) => t.textContent);
    expect(labels).toEqual(expect.arrayContaining(["intact", "DAN_PPL1", "MBON01"]));
    expect(valueLabel(0.05)).toBe("0.05");
  });
});

describe("sweepOutcome", () => {
  const counts = (done: number, failed: number, cancelled = 0) => ({ queued: 0, running: 0, done, failed, cancelled });
  it("states partial failures instead of hiding them", () => {
    expect(sweepOutcome({ total: 10, counts: counts(10, 0) })).toEqual({ text: "All 10 experiments finished.", kind: "info" });
    const partial = sweepOutcome({ total: 10, counts: counts(7, 3) });
    expect(partial.text).toContain("7 of 10");
    expect(partial.text).toContain("3 failed");
    expect(sweepOutcome({ total: 4, counts: counts(0, 4) }).text).toContain("All 4 experiments failed");
    const stopped = sweepOutcome({ total: 6, counts: counts(2, 0, 4) });
    expect(stopped).toEqual({ text: "Cancelled: 2 of 6 experiments finished; averages use those.", kind: "info" });
  });
});

// ---------------------------------------------------------------- protocols and lesions
describe("protocol text", () => {
  const preset = {
    steps: [{ phase: "pre", odour: "A" as const }, { phase: "training", odour: "A" as const, us: "shock" as const,
              us_onset_ms: -1200, us_ms: 1000 }, { phase: "extinction", odour: "A" as const, repeat: 6 }],
    readout: { plus: "A" as const, minus: "B" as const, before: "pre", after: "extinction" },
  };
  it("round-trips through the editable JSON", () => {
    const parsed = parseProtocolText(protocolText(preset));
    expect(typeof parsed).toBe("object");
    if (typeof parsed === "string") return;
    expect(parsed.steps).toHaveLength(3);
    expect(parsed.steps[1]).toMatchObject({ us: "shock", us_onset_ms: -1200, us_ms: 1000 });
    expect(parsed.steps[2]!.repeat).toBe(6);
    expect(parsed.readout).toEqual(preset.readout);
  });
  it("explains bad input instead of throwing", () => {
    expect(parseProtocolText("{not json")).toMatch(/^Protocol JSON:/);
    expect(parseProtocolText("[]")).toContain('"steps" list');
    expect(parseProtocolText('{"steps": []}')).toContain("at least one step");
    expect(parseProtocolText('{"steps": [{"odour": "A"}]}')).toContain('Step 1 needs a "phase"');
  });
  it("needs odour C when a compound step uses it", () => {
    document.body.innerHTML = `<select id="protocol"></select><div id="protocol-info"></div>
      <label id="cs-c-label"><input id="cs-c" value="odour_C"></label>
      <textarea id="protocol-json"></textarea><div id="lesions"></div>`;
    const picker = new ProtocolPicker([], { groups: [], cell_types: [] }, () => {});
    const json = document.getElementById("protocol-json") as HTMLTextAreaElement;
    json.value = '{"steps": [{"phase": "compound", "odour": "A+C", "us": "shock"}]}';
    json.dispatchEvent(new Event("input"));
    expect(picker.choice()).toMatchObject({ needsC: true });
    document.body.innerHTML = "";
  });
  it("encodes lesion menu values", () => {
    expect(decodeLesion(encodeLesion({ group: "APL" }))).toEqual({ group: "APL" });
    expect(decodeLesion(encodeLesion({ cell_type: "MBON:odd" }))).toEqual({ cell_type: "MBON:odd" });
  });
});

describe("ProtocolPicker", () => {
  it("returns the classic protocol, a preset's steps, odour C, and lesions", () => {
    document.body.innerHTML = `<select id="protocol"></select><div id="protocol-info"></div>
      <label id="cs-c-label"><input id="cs-c" value="odour_C"></label>
      <textarea id="protocol-json"></textarea><div id="lesions"></div>`;
    const presets: ProtocolPreset[] = [
      { name: "differential", title: "Differential", description: "d", in_flies: "f", in_model: "m",
        steps: [{ phase: "pre", odour: "A" as const }], readout: { plus: "A" as const, minus: "B" as const,
        before: "pre", after: "post" }, params: {}, extra_odour_slots: [] },
      { name: "second_order", title: "Second order", description: "d", in_flies: "f", in_model: "m",
        steps: [{ phase: "pre", odour: "C" as const }], readout: { plus: "C" as const, minus: "B" as const,
        before: "pre", after: "post" }, params: { plasticity_rule: "timing" }, extra_odour_slots: ["C"] },
    ];
    const onChange = vi.fn();
    const picker = new ProtocolPicker(presets, { groups: ["APL", "KC"], cell_types: ["MBON01"] }, onChange);
    expect(picker.choice()).toMatchObject({ steps: null, needsC: false });
    expect((document.getElementById("cs-c-label") as HTMLLabelElement).hidden).toBe(true);

    const select = document.getElementById("protocol") as HTMLSelectElement;
    select.value = "second_order";
    select.dispatchEvent(new Event("change"));
    const choice = picker.choice();
    expect(choice).toMatchObject({ needsC: true, params: { plasticity_rule: "timing" } });
    expect((document.getElementById("cs-c-label") as HTMLLabelElement).hidden).toBe(false);
    expect(document.getElementById("protocol-info")!.textContent).toContain("In this model");
    expect(onChange).toHaveBeenCalled();

    (document.getElementById("protocol-json") as HTMLTextAreaElement).value = "{broken";
    expect(picker.choice()).toMatch(/^Protocol JSON/);

    const boxes = document.querySelectorAll<HTMLInputElement>("#lesions input[type=checkbox]");
    expect([...boxes].map((b) => b.value)).toEqual(["group:KC", "group:APL", "type:MBON01"]);  // signal-flow order
    boxes[1]!.click();                                   // group APL
    boxes[2]!.click();                                   // cell type MBON01
    expect(picker.selectedLesions()).toEqual([{ group: "APL" }, { cell_type: "MBON01" }]);
    expect(document.querySelector(".lesion-summary")!.textContent).toBe("2 silenced");
    const filter = document.querySelector<HTMLInputElement>("#lesions input[type=search]")!;
    filter.value = "zzz";
    filter.dispatchEvent(new Event("input"));
    expect((boxes[2]!.parentElement as HTMLElement).hidden).toBe(true);
    document.body.innerHTML = "";
  });
});

describe("timeline US windows and protocol notes", () => {
  it("marks a shock that comes before the odour", () => {
    const root = document.createElement("div");
    const t = new Timeline(root, { onSeek: vi.fn(), onToggle: vi.fn(), onSpeed: vi.fn() });
    t.setExperiment([{ label: "A", slot: "A", us: "shock", phase: "training", t_start_ms: 4000,
                       t_end_ms: 5000, us_start_ms: 2800, us_end_ms: 3800 },
                     { label: "US", slot: null, us: "shock", phase: "training", t_start_ms: 6000,
                       t_end_ms: 6500, us_start_ms: 6000, us_end_ms: 6500 }], 10_000);
    const mark = root.querySelector<HTMLElement>(".us-mark")!;
    expect(mark.style.left).toBe("28%");
    expect(root.querySelectorAll(".us-mark")).toHaveLength(2);
    expect(describeEntry({ label: "US", slot: null, us: "shock", phase: "training", t_start_ms: 0,
                           t_end_ms: 1, us_start_ms: 0, us_end_ms: 1 })).toBe("training \u00b7 shock alone");
  });
  it("states the readout when it isn't the default, and lesions", () => {
    const res = { readout: { plus: "B", minus: "A", before: "after first training", after: "post" },
                  odours: { A: "octanol", B: "benzaldehyde" }, lesioned: [3, 4] } as unknown as ExperimentResult;
    const text = protocolLines(res).map((e) => e.textContent).join(" ");
    expect(text).toContain('benzaldehyde vs octanol, from phase "after first training" to "post"');
    expect(text).toContain("2 neurons silenced");
    const plain = { readout: { plus: "A", minus: "B", before: "pre", after: "post" }, odours: {},
                    lesioned: [] } as unknown as ExperimentResult;
    expect(protocolLines(plain)).toHaveLength(0);
  });
});
describe("ExperimentForm", () => {
  it("leaves APL gain to the server unless the slider is moved", () => {
    document.body.innerHTML = `<form id="f">
      <select id="odour-source"><option value="door">door</option><option value="random">random</option></select>
      <div><input id="cs-plus" value="ethyl acetate"></div><div><input id="cs-minus" value="1-octen-3-ol"></div>
      <input id="trials" value="3"><select id="us"><option value="shock">shock</option></select><input id="seed" value="1">
      <input id="apl-gain" type="range" min="0" max="0.2" step="0.001" value="0.05"><output id="apl-gain-value"></output>
      <button id="run-button"></button><p id="form-status"></p>
      <select id="protocol"></select><div id="protocol-info"></div>
      <label id="cs-c-label"><input id="cs-c" value="pentyl acetate"></label>
      <textarea id="protocol-json"></textarea><div id="lesions"></div></form>`;
    const form = new ExperimentForm(document.getElementById("f") as HTMLFormElement, {
      odoursAvailable: true, presets: [], lesionOptions: { groups: [], cell_types: [] }, defaultGain: 0.0059,
      catalog: [], onSubmit: vi.fn() });
    const slider = document.getElementById("apl-gain") as HTMLInputElement;
    expect(Number(slider.value)).toBeCloseTo(0.006, 3);              // starts at the server's value
    const untouched = form.read();
    if (typeof untouched === "string") throw new Error(untouched);
    expect(untouched.params?.graded_gain).toBeUndefined();
    slider.value = "0.1";
    slider.dispatchEvent(new Event("input"));
    const moved = form.read();
    if (typeof moved === "string") throw new Error(moved);
    expect(moved.params?.graded_gain).toBe(0.1);
    document.body.innerHTML = "";
  });
});

describe("API key field", () => {
  it("appears only when required, and sets and remembers the key", () => {
    document.body.innerHTML = `<label id="api-key-label" hidden><input id="api-key"></label>`;
    const api = new ApiClient("", vi.fn());
    setupApiKey(api, false);
    expect((document.getElementById("api-key-label") as HTMLLabelElement).hidden).toBe(true);
    saveKey("ff_old");
    setupApiKey(api, true);
    expect((document.getElementById("api-key-label") as HTMLLabelElement).hidden).toBe(false);
    expect(api.apiKey).toBe("ff_old");                          // remembered from before
    const input = document.getElementById("api-key") as HTMLInputElement;
    input.value = " ff_new ";
    input.dispatchEvent(new Event("change"));
    expect(api.apiKey).toBe("ff_new");
    expect(loadKey()).toBe("ff_new");
    input.value = "";
    input.dispatchEvent(new Event("change"));
    expect(api.apiKey).toBeNull();
    expect(loadKey()).toBeNull();
    document.body.innerHTML = "";
  });
});

describe("neuron click-through", () => {

  it("renders identity, partners and activity as text, links only real ids", async () => {
    const { renderNeuron } = await import("./neuronPanel");
    const root = document.createElement("aside");
    const evil = "<img src=x onerror=alert(1)>";
    const detail = { index: 5, root_id: "720575940612345678", flywire_id: "720575940612345678", region: "",
                     group: "MBON", cell_type: evil, side: "right",
                     transmitter: "GLUT", graded: false, input_synapses: 120, output_synapses: 0,
                     inputs: [{ cell_type: "KCg-m", group: "KC", neurons: 40, synapses: 100, sign: "excitatory" as const }],
                     outputs: [] };
    const onClose = vi.fn();
    renderNeuron(root, detail, { index: 5, total_spikes: 30, presentations: [
      { label: "octanol", phase: "pre", us: "none" as const, t_start_ms: 0, t_end_ms: 1000, spikes: 20, rate_hz: 20 },
      { label: "octanol", phase: "training", us: "shock" as const, t_start_ms: 2000, t_end_ms: 3000, spikes: 10, rate_hz: 10 }] },
      { codexLinks: true, onClose });
    expect(root.querySelector("img")).toBeNull();                  // names are text, never HTML
    expect(root.querySelector("h3")!.textContent).toBe(evil);
    expect(root.textContent).toContain("glutamate");
    expect(root.textContent).toContain("+ 20 more");                // 120 synapses, 100 listed
    expect(root.textContent).toContain("Outputs: none in the model");
    expect(root.querySelector("a")!.getAttribute("href")).toContain("root_id=720575940612345678");
    const bars = root.querySelectorAll<HTMLElement>(".bar-fill");
    expect(bars[0]!.style.width).toBe("100%");
    expect(root.textContent).toContain("20 Hz");
    expect(bars[1]!.classList.contains("us")).toBe(true);
    root.querySelector<HTMLButtonElement>("button.close")!.click();
    expect(onClose).toHaveBeenCalled();
    renderNeuron(root, detail, null, { codexLinks: false, onClose });
    expect(root.querySelector("a")).toBeNull();                     // synthetic ids: no link
    expect(root.textContent).toContain("Run or open an experiment");

    // a regional APL unit links to its parent neuron in FlyWire and names its region
    renderNeuron(root, { ...detail, root_id: "9000000000000000003", flywire_id: "720575940613583001", region: "ML",
                         group: "APL", cell_type: "APL", graded: true }, null, { codexLinks: true, onClose });
    expect(root.querySelector("a")!.getAttribute("href")).toContain("root_id=720575940613583001");
    expect(root.textContent).toContain("medial lobe part");
  });
});

describe("comparing experiments", () => {
  const base = { cs_plus: "octanol", cs_minus: "MCH", odour_source: "door", trials: 3, us: "shock", seed: 1,
                 params: { graded_gain: 0.01 }, lesions: [] as unknown[] };
  const detail = (id: string, request: object, extra: Record<string, unknown> = {}) => ({
    id, sweep_id: null, status: "done", progress: null, created_at: "2026-10-09T10:00:00Z", started_at: null,
    finished_at: null, error: null, request,
    result: { behavior: { valid: true, performance_index: 0.8 }, compartment_change: { valid: true, cs_plus: -0.6, cs_minus: -0.05 },
              separation: { kc_active_plus: 0.07, kc_correlation: 0.1 }, mean_weight_ratio: 0.95,
              mbon_weights: [{ index: 1, cell_type: "MBON01", weight_ratio: 0.5 }, { index: 2, cell_type: "MBON01", weight_ratio: 0.7 },
                             { index: 3, cell_type: "MBON11", weight_ratio: 0.9 }], ...extra },
  }) as unknown as ExperimentDetail;

  it("lists the settings that differ, not the seed", async () => {
    const { requestDiff } = await import("./compare");
    const diffs = requestDiff(base, { ...base, seed: 2, params: { graded_gain: 0.01, prediction_error: true },
                                      lesions: [{ group: "DAN_PPL1" }] });
    expect(requestDiff(base, { ...base, lesions: [{ group: "APL", cell_type: null }] })[0]!.b)
      .toBe('[{"group":"APL"}]');                                     // nulls inside values dropped
    expect(diffs).toEqual([
      { field: "lesions", a: "[]", b: '[{"group":"DAN_PPL1"}]' },
      { field: "params.prediction_error", a: "default", b: "true" },
    ]);
  });

  it("compares outcomes and per-type learning", async () => {
    const { metricRows, mbonLearning } = await import("./compare");
    const a = detail("a", base);
    const b = detail("b", { ...base, lesions: [{ group: "DAN_PPL1" }] }, {
      behavior: { valid: false, performance_index: null },
      mbon_weights: [{ index: 1, cell_type: "MBON01", weight_ratio: 1.0 }, { index: 3, cell_type: "MBON11", weight_ratio: 0.85 },
                     { index: 9, cell_type: "MBON99", weight_ratio: 1.0 }] });
    expect(metricRows(a, b)[0]).toMatchObject({ a: 0.8, b: null });     // invalid prediction: n/a, not 0
    const learning = mbonLearning(a, b);
    expect(learning.map((l) => l.cell_type)).toEqual(["MBON01", "MBON11"]);   // biggest change first; MBON99 only in B
    expect(learning[0]!.a).toBeCloseTo(0.6);
  });

  it("offers only other finished stand-alone experiments, and renders text only", async () => {
    const { compareMenu, renderComparison } = await import("./compare");
    const list = [detail("a", base), detail("b", base), { ...detail("c", base), status: "running" },
                  { ...detail("d", base), sweep_id: "s1" }] as unknown as ExperimentSummary[];
    const onPick = vi.fn();
    const menu = compareMenu(list, "a", onPick)!;
    expect([...menu.options].map((o) => o.value)).toEqual(["", "b"]);
    menu.value = "b";
    menu.dispatchEvent(new Event("change"));
    expect(onPick).toHaveBeenCalledWith("b");
    expect(compareMenu([detail("a", base)] as unknown as ExperimentSummary[], "a", onPick)).toBeNull();

    const root = document.createElement("div");
    const evil = "<img src=x onerror=alert(1)>";
    const onBack = vi.fn();
    renderComparison(root, detail("a", { ...base, cs_plus: evil }), detail("b", { ...base, seed: 7 }), onBack);
    expect(root.querySelector("img")).toBeNull();
    expect(root.textContent).toContain(evil);
    expect(root.textContent).toContain("Seeds 1 and 7");
    const { describeExperiment } = await import("./history");
    expect(describeExperiment(detail("x", { ...base, lesions: [{ group: "DAN_PPL1" }] })))
      .toContain("DAN_PPL1 silenced");
    root.querySelector<HTMLButtonElement>("button")!.click();
    expect(onBack).toHaveBeenCalled();
  });
});
