import { describe, expect, it } from "vitest";

import { groupCentres, groupLinks, groupPartners, groupRoles, neuronLinks, neuronRoles } from "./explorer";
import { applyFrame, boundsOf, frameFromBounds, toScene } from "./geometry";
import { decodeMorphology, shapeIndex } from "./morphology";
import { pickNearest } from "./picking";
import type { GroupConnection, NeuronConnections, NeuronTable } from "./types";

/** A morphology file as scripts/build_anatomy.py writes it (see tests/test_build_anatomy.py). */
function encode(origin: number[], step: number, neurons: { id: string; q: number[][]; parent: number[] }[]): ArrayBuffer {
  const v = neurons.reduce((s, n) => s + n.q.length, 0);
  const roots = neurons.flatMap((n) => n.q.filter((_, i) => n.parent[i]! < 0));
  let header = JSON.stringify({ origin, step_nm: step, root_id: neurons.map((n) => n.id),
                                vertices: neurons.map((n) => n.q.length), roots: roots.length });
  header += " ".repeat((4 - (header.length % 4)) % 4);
  const head = new TextEncoder().encode(header);
  const buf = new ArrayBuffer(12 + head.length + 8 * v + 6 * roots.length);
  const bytes = new Uint8Array(buf);
  bytes.set(new TextEncoder().encode("FFMORPH2"), 0);
  new DataView(buf).setUint32(8, head.length, true);
  bytes.set(head, 12);
  const off = 12 + head.length;
  const d = new Int16Array(buf, off, 3 * v);
  const up = new Uint16Array(buf, off + 6 * v, v);
  const r = new Uint16Array(buf, off + 8 * v, 3 * roots.length);
  let g = 0;
  for (const n of neurons) {
    n.q.forEach((p, i) => {
      const par = n.parent[i]!;
      up[g] = par < 0 ? 0 : i - par;
      for (let a = 0; a < 3; a++) d[a * v + g] = par < 0 ? 0 : p[a]! - n.q[par]![a]!;
      g++;
    });
  }
  roots.forEach((p, k) => r.set(p, k * 3));
  return buf;
}

describe("morphology file", () => {
  it("decodes positions and parents", () => {
    const buf = encode([1000, 2000, 3000], 10, [
      { id: "111", q: [[0, 0, 0], [5, 0, 0], [5, 7, 0], [9, 0, 0]], parent: [-1, 0, 1, 1] },
      { id: "222", q: [], parent: [] },
      { id: "333", q: [[100, 200, 300], [101, 200, 300]], parent: [-1, 0] },
    ]);
    const m = decodeMorphology(buf);
    expect(m.rootIds).toEqual(["111", "222", "333"]);
    expect(Array.from(m.count)).toEqual([4, 0, 2]);
    expect(Array.from(m.start)).toEqual([0, 4, 4]);
    expect(Array.from(m.parent)).toEqual([-1, 0, 1, 1, -1, 4]);
    expect(Array.from(m.positions.subarray(6, 9))).toEqual([1050, 2070, 3000]);       // [5, 7, 0]
    expect(Array.from(m.positions.subarray(12, 15))).toEqual([2000, 4000, 6000]);     // second root
    expect(() => decodeMorphology(new ArrayBuffer(16))).toThrow(/not a morphology file/);
  });

  it("maps table neurons to shapes by FlyWire id; units of one neuron share it", () => {
    const m = decodeMorphology(encode([0, 0, 0], 1, [
      { id: "111", q: [[0, 0, 0]], parent: [-1] }, { id: "222", q: [], parent: [] }]));
    expect(Array.from(shapeIndex(m, ["111", "222", "999", "111"]))).toEqual([0, -1, -1, 0]);
  });
});

describe("scene frame", () => {
  it("centres, scales to 2 units and turns the brain upright", () => {
    const f = frameFromBounds([0, 0, 0], [100, 50, 20]);
    expect(f.scale).toBeCloseTo(0.02);
    const p = applyFrame(f, [100, 50, 20, 0, 0, 0]);
    expect(Array.from(p)).toEqual([1, -0.5, -0.2, -1, 0.5, 0.2].map((x) => Math.fround(x)));
  });

  it("finds bounds, skipping unknown positions", () => {
    expect(boundsOf([1, 2, 3, NaN, 0, 0, -1, 5, 0])).toEqual({ lo: [-1, 2, 0], hi: [1, 5, 3] });
  });

  it("places neurons in a given frame", () => {
    const table = { count: 2, x: [0, null], y: [0, 0], z: [0, 0] } as unknown as NeuronTable;
    const s = toScene(table, frameFromBounds([-10, -10, -10], [10, 10, 10]));
    expect(Array.from(s.valid)).toEqual([1, 0]);
    expect(Array.from(s.positions.subarray(0, 3))).toEqual([0, -0, -0]);
  });
});

describe("picking", () => {
  // identity view-projection: scene x, y in -1..1 map straight onto the canvas
  const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const points = new Float32Array([0, 0, 0.5, 0.02, 0, -0.5, 0.9, 0.9, 0]);
  const owner = new Int32Array([7, 8, 9]);

  it("takes the point nearest the cursor; within half a pixel, the nearest to the camera", () => {
    expect(pickNearest(points, owner, I, 100, 100, 50, 50, 3, () => 1)).toBe(7);
    expect(pickNearest(points, owner, I, 100, 100, 51, 50, 3, () => 1)).toBe(8);     // 0.02 -> x = 51
    expect(pickNearest(points, owner, I, 1000, 1000, 505, 500, 6, () => 1)).toBe(8);
    expect(pickNearest(new Float32Array([0, 0, 0.5, 0, 0, -0.5]), new Int32Array([1, 2]), I, 100, 100,
                       50, 50, 3, () => 1)).toBe(2);                                 // same spot: the front one
  });

  it("ignores hidden neurons, prefers highlighted ones, and returns null far from everything", () => {
    expect(pickNearest(points, owner, I, 100, 100, 50, 50, 3, (n) => (n === 7 ? 0 : 1))).toBe(8);
    expect(pickNearest(points, owner, I, 100, 100, 50, 50, 3, (n) => (n === 8 ? 2 : 1))).toBe(8);
    expect(pickNearest(points, owner, I, 100, 100, 20, 80, 3, () => 1)).toBeNull();
  });
});

describe("connection explorer", () => {
  const conns: NeuronConnections = {
    index: 0, min_synapses: 1, total_inputs: 2, total_outputs: 2,
    inputs: [{ index: 1, synapses: 20, sign: "excitatory" }, { index: 2, synapses: 5, sign: "inhibitory" }],
    outputs: [{ index: 2, synapses: 10, sign: "excitatory" }, { index: 3, synapses: 1, sign: "excitatory" }],
    dopamine_to: [], dopamine_from: [4],
  };
  const anchor = (i: number): [number, number, number] | null => (i === 3 ? null : [i, 0, 0]);

  it("gives each partner a role", () => {
    const roles = neuronRoles(0, conns);
    expect(Object.fromEntries(roles)).toEqual({ 0: "selected", 1: "input", 2: "both", 3: "output", 4: "dopamine" });
  });

  it("draws tubes toward the receiving neuron, thicker for more synapses", () => {
    const links = neuronLinks(0, conns, anchor);
    expect(links.map((l) => [l.role, l.from[0], l.to[0], l.weight])).toEqual([
      ["input", 1, 0, 1], ["input", 2, 0, 0.25], ["output", 0, 2, 0.5],          // neuron 3: no position
      ["dopamine", 4, 0, 0.3],
    ]);
    expect(neuronLinks(0, conns, anchor, 1).filter((l) => l.role === "input")).toHaveLength(1);
    expect(neuronLinks(3, conns, anchor)).toEqual([]);
  });

  const rows: GroupConnection[] = [
    { pre: "PN", post: "KC", synapses: 300, connections: 30, sign: "excitatory" },
    { pre: "KC", post: "MBON", synapses: 150, connections: 60, sign: "excitatory" },
    { pre: "KC", post: "KC", synapses: 90, connections: 9, sign: "excitatory" },
    { pre: "APL", post: "KC", synapses: 60, connections: 6, sign: "inhibitory" },
    { pre: "KC", post: "APL", synapses: 30, connections: 3, sign: "excitatory" },
    { pre: "DAN", post: "MBON", synapses: 0, connections: 12, sign: "dopamine" },
  ];

  it("lists a group's partners by direction, strongest first", () => {
    const p = groupPartners("KC", rows);
    expect(p.inputs.map((r) => r.pre)).toEqual(["PN", "KC", "APL"]);
    expect(p.outputs.map((r) => r.post)).toEqual(["MBON", "KC", "APL"]);
    expect(groupPartners("MBON", rows).inputs.map((r) => r.pre)).toEqual(["KC", "DAN"]);
  });

  it("highlights member and partner groups", () => {
    const groups = ["PN", "KC", "KC", "MBON", "APL", "DAN", "ORN"];
    expect(Object.fromEntries(groupRoles("KC", groups, rows)))
      .toEqual({ 0: "input", 1: "member", 2: "member", 3: "output", 4: "both" });
    expect(groupRoles("MBON", groups, rows).get(5)).toBe("dopamine");
  });

  it("joins group centres in each hemisphere, skipping connections within the group", () => {
    const groups = ["PN", "PN", "KC", "KC", "MBON"];
    const pos: [number, number, number][] = [[-2, 0, 0], [2, 0, 0], [-1, 1, 0], [1, 1, 0], [3, 0, 0]];
    const centres = groupCentres(groups, (i) => pos[i]!);
    expect(centres.get("KC|left")).toEqual([-1, 1, 0]);
    expect(centres.has("MBON|left")).toBe(false);
    const links = groupLinks("KC", rows, centres);
    // left: PN -> KC; right: PN -> KC and KC -> MBON. No KC -> KC, and no APL (no neurons).
    expect(links.map((l) => `${l.role}:${l.from[0]}->${l.to[0]}`)).toEqual(
      ["input:-2->-1", "input:2->1", "output:1->3"]);
    expect(links[0]!.weight).toBe(1);
    expect(links[2]!.weight).toBe(0.5);
  });
});
