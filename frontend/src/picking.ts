// picking.ts — which neuron is under the cursor.
//
// Neurons are drawn as thousands of thin lines (1.8 million line points on the
// FlyWire circuit). Ray-casting that many segments is slow, so picking works in
// screen space: project every candidate point with the camera's matrix and take the
// one nearest the cursor, within a few pixels.

/** How a neuron takes part in picking: 0 not pickable (hidden), 1 normal, 2 preferred
 *  (highlighted neurons win over dimmed ones under the same cursor). */
export type PickTier = 0 | 1 | 2;

/**
 * Owner of the point nearest (cx, cy), or null if none is within radiusPx.
 *
 * points    x, y, z per point (scene coordinates)
 * owner     neuron index of each point
 * viewProj  camera projection x view matrix, column-major (THREE.Matrix4.elements)
 * width, height, cx, cy   canvas size and cursor position, in CSS pixels
 * tier      PickTier of each neuron
 */
export function pickNearest(points: Float32Array, owner: Int32Array, viewProj: ArrayLike<number>,
                            width: number, height: number, cx: number, cy: number, radiusPx: number,
                            tier: (neuron: number) => PickTier): number | null {
  const e = viewProj;
  const r2 = radiusPx * radiusPx;
  let best = -1;
  let bestTier = 0;
  let bestD2 = Infinity;
  let bestDepth = Infinity;
  const tierOf = new Map<number, PickTier>();
  for (let k = 0; k < owner.length; k++) {
    const n = owner[k]!;
    let t = tierOf.get(n);
    if (t === undefined) {
      t = tier(n);
      tierOf.set(n, t);
    }
    if (t === 0 || t < bestTier) continue;
    const x = points[k * 3]!, y = points[k * 3 + 1]!, z = points[k * 3 + 2]!;
    const w = e[3]! * x + e[7]! * y + e[11]! * z + e[15]!;
    if (w <= 0) continue;                                   // behind the camera
    const sx = ((e[0]! * x + e[4]! * y + e[8]! * z + e[12]!) / w + 1) * 0.5 * width;
    const sy = (1 - (e[1]! * x + e[5]! * y + e[9]! * z + e[13]!) / w) * 0.5 * height;
    const d2 = (sx - cx) ** 2 + (sy - cy) ** 2;
    if (d2 > r2) continue;
    const depth = (e[2]! * x + e[6]! * y + e[10]! * z + e[14]!) / w;
    // a higher tier always wins; then the nearest on screen; within half a pixel, the nearest to the camera
    if (t > bestTier || d2 < bestD2 - 0.25 || (Math.abs(d2 - bestD2) <= 0.25 && depth < bestDepth)) {
      best = n;
      bestTier = t;
      bestD2 = d2;
      bestDepth = depth;
    }
  }
  return best >= 0 ? best : null;
}
