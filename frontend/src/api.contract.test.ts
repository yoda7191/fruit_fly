// @vitest-environment node
//
// Contract test: runs the typed client against a live backend and checks that
// responses really have the shapes declared in types.ts. Skipped unless
// FRUIT_FLY_API_URL is set:
//
//   uvicorn backend.app.main:app            (repository root, another terminal)
//   FRUIT_FLY_API_URL=http://127.0.0.1:8000 npx vitest run src/api.contract.test.ts

import { describe, expect, it } from "vitest";

import { ApiClient, ApiError } from "./api";
import { SpikePlayer } from "./playback";

const base = process.env.FRUIT_FLY_API_URL;

type Kind = "string" | "number" | "boolean" | "array" | "object" | "nullable-number" | "nullable-object";

function expectShape(value: unknown, spec: Record<string, Kind>, where: string): void {
  expect(value, where).toBeTypeOf("object");
  const obj = value as Record<string, unknown>;
  for (const [key, kind] of Object.entries(spec)) {
    const v = obj[key];
    const label = `${where}.${key}`;
    switch (kind) {
      case "array": expect(Array.isArray(v), label).toBe(true); break;
      case "object": expect(v !== null && typeof v === "object", label).toBe(true); break;
      case "nullable-number": expect(v === null || typeof v === "number", label).toBe(true); break;
      case "nullable-object": expect(v === null || typeof v === "object", label).toBe(true); break;
      default: expect(typeof v, label).toBe(kind);
    }
  }
}

describe.skipIf(!base)("API contract (live backend)", () => {
  const api = new ApiClient(base);

  it("neuron detail", async () => {
    const d = await api.neuron(0);
    expectShape(d, { index: "number", root_id: "string", flywire_id: "string", region: "string", group: "string", cell_type: "string", side: "string",
                     transmitter: "string", graded: "boolean", input_synapses: "number", output_synapses: "number",
                     inputs: "array", outputs: "array" }, "neuron");
    const p = d.outputs[0] ?? d.inputs[0];
    if (p) expectShape(p, { cell_type: "string", group: "string", neurons: "number", synapses: "number",
                            sign: "string" }, "partner");
  });

  it("connections, group connectivity, odour catalogue", async () => {
    const c = await api.connections(0, 1, 5);
    expectShape(c, { index: "number", min_synapses: "number", total_inputs: "number", total_outputs: "number",
                     inputs: "array", outputs: "array", dopamine_to: "array", dopamine_from: "array" }, "connections");
    const p = c.inputs[0] ?? c.outputs[0];
    if (p) expectShape(p, { index: "number", synapses: "number", sign: "string" }, "connection");
    const rows = await api.connectivity();
    expect(rows.length).toBeGreaterThan(0);
    expectShape(rows[0], { pre: "string", post: "string", synapses: "number", connections: "number", sign: "string" },
                "group connection");
    const summary = await api.circuit();
    expectShape(summary.anatomy, { regions: "boolean", morphology: "boolean" }, "anatomy");
    if (summary.odours_loaded) {
      const items = await api.odourCatalog();
      expectShape(items[0], { name: "string", chemical_class: "string", coverage: "number" }, "catalogue item");
    }
  });

  it("anatomy files, when the circuit has them", async () => {
    const summary = await api.circuit();
    if (summary.anatomy?.regions) {
      const regions = await api.regions();
      expectShape(regions.regions[0], { name: "string", region: "string", side: "string", label: "string",
                                        olfactory: "boolean", vertices: "array", triangles: "array" }, "region");
    }
    if (summary.anatomy?.morphology) {
      const { decodeMorphology } = await import("./morphology");
      const m = decodeMorphology(await api.morphology());
      const table = await api.neurons();
      expect(m.rootIds.length).toBeGreaterThan(0);
      expect(new Set(m.rootIds).size).toBe(m.rootIds.length);
      expect(m.rootIds.some((id) => (table.flywire_id ?? table.root_id).includes(id))).toBe(true);
    }
  });

  it("health", async () => {
    expectShape(await api.health(), { status: "string", neurons: "number", odours_loaded: "boolean",
                                      queue: "string", queue_ok: "boolean", database: "string",
                                      auth_required: "boolean", rate_limit_per_min: "number" }, "health");
  });

  it("circuit and neuron table", async () => {
    const circuit = await api.circuit();
    expectShape(circuit, { neurons: "number", fast_synapses: "number", plastic_synapses: "number",
                           groups: "object", odours_loaded: "boolean" }, "circuit");
    const table = await api.neurons();
    expectShape(table, { count: "number", root_id: "array", group: "array", cell_type: "array",
                         x: "array", y: "array", z: "array", bounds: "nullable-object" }, "neurons");
    expect(table.count).toBe(circuit.neurons);
    expect(table.root_id.every((r) => typeof r === "string")).toBe(true);
  });

  it("odours and error format", async () => {
    const circuit = await api.circuit();
    if (!circuit.odours_loaded) return;
    const list = await api.odours("octanol", 10);
    expectShape(list, { total: "number", offset: "number", limit: "number", items: "array" }, "odours");
    expectShape(list.items[0], { name: "string", coverage: "number" }, "odours.items[0]");
    const err = await api.submitConditioning({ cs_plus: "octanol", cs_minus: "benzaldehyde",
      odour_source: "door", trials: 1, us: "shock", seed: 1 }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).suggestions).toContain("3-octanol");
  });

  it("experiment lifecycle and spikes", { timeout: 120_000 }, async () => {
    const job = await api.submitConditioning({
      cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 1,
      protocol: { stim_ms: 400, gap_ms: 600, settle_ms: 100 },
    });
    expectShape(job, { id: "string", sweep_id: "nullable-object", status: "string", progress: "nullable-object",
                       created_at: "string", request: "object" }, "summary");
    const detail = await api.waitForExperiment(job.id, { intervalMs: 200 });
    expect(detail.progress).toEqual({ done: 6, total: 6 });      // 1 trial: 2 + 2 + 2
    const res = detail.result!;
    expectShape(res, { separation: "object", mbons: "array", compartment_change: "object",
                       mean_weight_ratio: "nullable-number", mbon_weights: "array", timeline: "array",
                       duration_ms: "number", n_spikes: "number", coverage: "nullable-object",
                       input_similarity: "nullable-number" }, "result");
    expectShape(res.timeline[0], { label: "string", us: "string", phase: "string",
                                   t_start_ms: "number", t_end_ms: "number" }, "timeline[0]");
    expectShape(res, { readout: "object", readout_after_ms: "number", odours: "object", lesioned: "array" }, "result");
    expectShape(res.mbons[0], { cell_type: "string", n: "number", us_target: "boolean",
                                pre_plus: "number", post_minus: "number" }, "mbons[0]");
    expectShape(res.behavior, { naive: "object", trained: "object", learned_drive: "number",
                                performance_index: "number", flies: "number",
                                sampled_performance_index: "number" }, "behavior");
    expectShape(res.behavior.trained, { drive_plus: "nullable-number", drive_minus: "nullable-number",
                                        p_plus: "number", preference: "number" }, "behavior.trained");

    const w = await api.spikes(job.id, 0, 500, ["KC", "MBON"]);
    expectShape(w, { t0_ms: "number", t1_ms: "number", count: "number", truncated: "boolean",
                     neurons: "array", times_ms: "array" }, "spikes");
    expect(w.neurons).toHaveLength(w.count);
    expect([...w.times_ms].sort((a, b) => a - b)).toEqual(w.times_ms);

    const listed = await api.experiments();
    expect(listed.some((e) => e.id === job.id)).toBe(true);
    const page = await api.experimentPage({ limit: 1 });
    expectShape(page, { items: "array" }, "page");
    expect(page.next_cursor === null || typeof page.next_cursor === "string").toBe(true);
    // an identical request returns the stored experiment
    const again = await api.submitConditioning({ ...job.request });
    expect(again.id).toBe(job.id);
    for (const url of Object.values(api.exportUrls(job.id))) {
      const r = await fetch(url);
      expect(r.status, url).toBe(200);
    }
    await expect(api.cancelExperiment(job.id)).rejects.toMatchObject({ status: 409 });
    await api.deleteExperiment(job.id);
    await expect(api.experiment(job.id)).rejects.toMatchObject({ status: 404 });
  });

  it("playback replays every recorded spike exactly once", { timeout: 120_000 }, async () => {
    const job = await api.submitConditioning({
      cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 2,
      protocol: { stim_ms: 400, gap_ms: 600, settle_ms: 100 },
    });
    const res = (await api.waitForExperiment(job.id, { intervalMs: 200 })).result!;
    const player = new SpikePlayer(res.duration_ms,
      (t0, t1, signal) => api.spikes(job.id, t0, t1, undefined, 2_000_000, signal),
      { chunkMs: 700 });
    player.speed = 20;
    player.play();
    let emitted = 0;
    let lastTime = -1;
    let ordered = true;
    while (!player.finished) {
      player.advance(16, (_n, t) => {
        emitted++;
        if (t < lastTime) ordered = false;
        lastTime = t;
      });
      if (player.error) throw player.error;
      await new Promise((r) => setTimeout(r, 0));
    }
    expect(player.truncatedChunks).toBe(0);
    expect(ordered).toBe(true);
    expect(emitted).toBe(res.n_spikes);
    await api.deleteExperiment(job.id);
  });

  it("protocol presets, lesion options and a backward-pairing protocol", { timeout: 120_000 }, async () => {
    const presets = await api.protocols();
    expect(presets.length).toBeGreaterThan(3);
    expectShape(presets[0], { name: "string", title: "string", in_flies: "string", in_model: "string",
                              steps: "array", readout: "object", params: "object",
                              extra_odour_slots: "array" }, "preset");
    const options = await api.lesionOptions();
    expectShape(options, { groups: "array", cell_types: "array" }, "lesion options");

    const backward = presets.find((p) => p.name === "backward_pairing")!;
    const job = await api.submitConditioning({
      cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 1,
      protocol: { stim_ms: 400, gap_ms: 400, settle_ms: 100 },
      steps: backward.steps, readout: backward.readout, params: backward.params as never,
      lesions: [{ group: options.groups.includes("DPM") ? "DPM" : options.groups[0]! }],
    });
    const res = (await api.waitForExperiment(job.id, { intervalMs: 200 })).result!;
    const shocked = res.timeline.find((t) => t.us === "shock")!;
    expect(shocked.us_end_ms!).toBeLessThan(shocked.t_start_ms);          // shock before the odour
    expect(res.lesioned.length).toBeGreaterThan(0);
    await api.deleteExperiment(job.id);
  });

  it("sweep lifecycle", { timeout: 180_000 }, async () => {
    const created = await api.createSweep({
      base: { cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 1,
              protocol: { stim_ms: 400, gap_ms: 600, settle_ms: 100 } },
      parameter: "params.graded_gain", values: [0, 0.05], repeats: 1,
    });
    expectShape(created, { id: "string", parameter: "string", values: "array", repeats: "number",
                           total: "number", counts: "object", status: "string", base: "object" }, "sweep");
    const done = await api.waitForSweep(created.id, { intervalMs: 300 });
    expect(done.counts.done).toBe(2);
    expectShape(done.points[0], { value: "number", done: "number", metrics: "object" }, "points[0]");
    expectShape(done.points[0]!.metrics.performance_index, { mean: "nullable-number", n: "number" }, "metric");
    const csv = await fetch(api.sweepCsvUrl(created.id)).then((r) => r.text());
    expect(csv.trim().split("\n")).toHaveLength(3);
    expect((await api.sweeps()).some((s) => s.id === created.id)).toBe(true);
    await api.deleteSweep(created.id);
  });

  it("lesion scan: string values", { timeout: 180_000 }, async () => {
    const options = await api.lesionOptions();
    const created = await api.createSweep({
      base: { cs_plus: "A", cs_minus: "B", odour_source: "random", trials: 1, us: "shock", seed: 1,
              protocol: { stim_ms: 400, gap_ms: 600, settle_ms: 100 } },
      parameter: "lesion", values: ["none", `group:${options.groups[0]}`], repeats: 1,
    });
    const done = await api.waitForSweep(created.id, { intervalMs: 300 });
    expect(done.counts.done).toBe(2);
    expect(done.values).toEqual(["none", `group:${options.groups[0]}`]);
    expectShape(done.points[1], { value: "string", done: "number", metrics: "object" }, "points[1]");
    await api.deleteSweep(created.id);
  });
});