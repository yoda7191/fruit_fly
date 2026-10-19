// morphology.ts — reads mb_morphology.bin, every neuron's simplified skeleton.
//
// Format (scripts/build_anatomy.py; little-endian):
//   "FFMORPH2", uint32 header length H, H bytes of JSON
//   {origin: [x,y,z], step_nm, root_id: [...], vertices: [count per neuron], roots: R},
//   then for all V vertices (each neuron's depth-first, so a parent usually comes
//   right before its child):
//   int16 dx[V], dy[V], dz[V]   offset from the parent in step_nm units (0 at roots)
//   uint16 up[V]                steps back to the parent; 0 = a root
//   uint16 xyz[R*3]             each root's position: nm = origin + q * step_nm

const MAGIC = "FFMORPH2";

export interface Morphology {
  rootIds: string[];          // FlyWire id of each neuron in the file
  start: Uint32Array;         // first vertex of each neuron
  count: Uint32Array;         // vertices of each neuron (0: no skeleton)
  positions: Float32Array;    // x, y, z per vertex, nm in FlyWire space
  parent: Int32Array;         // global index of each vertex's parent; -1 for a root
}

interface Header {
  origin: [number, number, number];
  step_nm: number;
  root_id: string[];
  vertices: number[];
  roots: number;
}

export function decodeMorphology(buffer: ArrayBuffer): Morphology {
  const bytes = new Uint8Array(buffer);
  if (new TextDecoder().decode(bytes.subarray(0, 8)) !== MAGIC) throw new Error("not a morphology file");
  const view = new DataView(buffer);
  const h = view.getUint32(8, true);
  const head = JSON.parse(new TextDecoder().decode(bytes.subarray(12, 12 + h))) as Header;
  const n = head.vertices.length;
  const v = head.vertices.reduce((a, b) => a + b, 0);
  const off = 12 + h;
  // Typed-array views need aligned offsets; the header is padded to 4 bytes and the
  // sections are 2-byte values, so slices are aligned (copy only if a platform isn't).
  const i16 = new Int16Array(buffer.slice(off, off + 6 * v));
  const up = new Uint16Array(buffer.slice(off + 6 * v, off + 8 * v));
  const roots = new Uint16Array(buffer.slice(off + 8 * v, off + 8 * v + 6 * head.roots));

  const q = new Int32Array(v * 3);
  const parent = new Int32Array(v);
  let r = 0;
  for (let i = 0; i < v; i++) {
    const back = up[i]!;
    if (back === 0) {
      parent[i] = -1;
      q[i * 3] = roots[r * 3]!;
      q[i * 3 + 1] = roots[r * 3 + 1]!;
      q[i * 3 + 2] = roots[r * 3 + 2]!;
      r++;
    } else {
      const p = i - back;
      parent[i] = p;
      q[i * 3] = q[p * 3]! + i16[i]!;
      q[i * 3 + 1] = q[p * 3 + 1]! + i16[v + i]!;
      q[i * 3 + 2] = q[p * 3 + 2]! + i16[2 * v + i]!;
    }
  }
  const positions = new Float32Array(v * 3);
  const [ox, oy, oz] = head.origin;
  const s = head.step_nm;
  for (let i = 0; i < v; i++) {
    positions[i * 3] = ox + q[i * 3]! * s;
    positions[i * 3 + 1] = oy + q[i * 3 + 1]! * s;
    positions[i * 3 + 2] = oz + q[i * 3 + 2]! * s;
  }

  const start = new Uint32Array(n);
  const count = Uint32Array.from(head.vertices);
  for (let k = 1; k < n; k++) start[k] = start[k - 1]! + count[k - 1]!;
  return { rootIds: head.root_id, start, count, positions, parent };
}

/** Morphology index of every neuron in the table (-1: no shape). Model units that stand
 *  for part of a neuron (regional APL) share their neuron's shape. */
export function shapeIndex(m: Morphology, flywireIds: string[]): Int32Array {
  const byId = new Map(m.rootIds.map((id, k) => [id, k]));
  return Int32Array.from(flywireIds, (id) => {
    const k = byId.get(id);
    return k !== undefined && m.count[k]! > 0 ? k : -1;
  });
}
