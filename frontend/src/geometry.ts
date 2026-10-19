// geometry.ts — FlyWire coordinates -> scene coordinates.
//
// Everything drawn (neuron dots, neuron shapes, brain regions, connections) goes
// through one SceneFrame, so it all lines up.

import type { NeuronTable } from "./types";

export interface ScenePositions {
  /** xyz per neuron, in the scene frame. */
  positions: Float32Array;
  /** 1 if the neuron has a known position. */
  valid: Uint8Array;
}

/**
 * Center a box at the origin and scale it so its largest extent is 2 units. FlyWire's
 * y axis points down (image rows) and z into the stack; flipping both (a 180°
 * rotation about x, so still right-handed) shows the brain upright, seen from the front.
 */
export interface SceneFrame {
  center: [number, number, number];
  scale: number;
}

const SIGN = [1, -1, -1] as const;

export function frameFromBounds(lo: ArrayLike<number>, hi: ArrayLike<number>): SceneFrame {
  const center: [number, number, number] = [0, 1, 2].map((a) => (lo[a]! + hi[a]!) / 2) as [number, number, number];
  const extent = Math.max(...[0, 1, 2].map((a) => hi[a]! - lo[a]!));
  return { center, scale: extent > 0 ? 2 / extent : 1 };
}

/** Bounds of a flat x, y, z, ... array (Infinity / -Infinity if empty; non-finite values skipped). */
export function boundsOf(xyz: ArrayLike<number>): { lo: number[]; hi: number[] } {
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    if (!Number.isFinite(xyz[i]!) || !Number.isFinite(xyz[i + 1]!) || !Number.isFinite(xyz[i + 2]!)) continue;
    for (let a = 0; a < 3; a++) {
      const v = xyz[i + a]!;
      if (v < lo[a]!) lo[a] = v;
      if (v > hi[a]!) hi[a] = v;
    }
  }
  return { lo, hi };
}

/** Transform a flat x, y, z, ... array of FlyWire coordinates into the scene frame. */
export function applyFrame(frame: SceneFrame, xyz: ArrayLike<number>, out = new Float32Array(xyz.length)): Float32Array {
  const { center, scale } = frame;
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    for (let a = 0; a < 3; a++) out[i + a] = SIGN[a]! * (xyz[i + a]! - center[a]!) * scale;
  }
  return out;
}

/** The frame that fits every neuron with a known position. */
export function neuronFrame(table: NeuronTable): SceneFrame | null {
  const xyz: number[] = [];
  for (let i = 0; i < table.count; i++) {
    const p = [table.x[i], table.y[i], table.z[i]];
    if (p.every((v) => typeof v === "number" && Number.isFinite(v))) xyz.push(...(p as number[]));
  }
  if (!xyz.length) return null;
  const { lo, hi } = boundsOf(xyz);
  return frameFromBounds(lo, hi);
}

/** Neuron positions in `frame` (default: the frame fitting the neurons). */
export function toScene(table: NeuronTable, frame: SceneFrame | null = neuronFrame(table)): ScenePositions {
  const n = table.count;
  const positions = new Float32Array(n * 3);
  const valid = new Uint8Array(n);
  if (!frame) return { positions, valid };
  const p = new Float32Array(3);
  for (let i = 0; i < n; i++) {
    const x = table.x[i], y = table.y[i], z = table.z[i];
    if (typeof x !== "number" || typeof y !== "number" || typeof z !== "number" ||
        !Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    valid[i] = 1;
    applyFrame(frame, [x, y, z], p);
    positions.set(p, i * 3);
  }
  return { positions, valid };
}
