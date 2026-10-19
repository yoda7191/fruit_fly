// explorer.ts — what the connection explorer highlights and draws, as plain data.
//
// A selected neuron: its input partners (sky blue), output partners (orange), both
// (pink) and dopamine partners (lime) light up, the rest of the brain dims, and a
// tube runs from each partner to it (inputs) or from it to each partner (outputs).
// A selected group: its member neurons and partner groups light up, and a tube runs
// between the groups' centres in each hemisphere.

import type { GroupConnection, NeuronConnections } from "./types";
import type { Role } from "./colors";
import type { Link } from "./viewer";

type Vec3 = [number, number, number];

/** Dopamine partners drawn (an MBON can get dopamine from 70+ DANs; they all highlight). */
export const DOPAMINE_LINKS = 20;

/** Roles of the neurons around one selected neuron. */
export function neuronRoles(index: number, c: NeuronConnections): Map<number, Role> {
  const roles = new Map<number, Role>();
  for (const p of c.inputs) roles.set(p.index, "input");
  for (const p of c.outputs) roles.set(p.index, roles.get(p.index) === "input" ? "both" : "output");
  for (const d of [...c.dopamine_to, ...c.dopamine_from]) if (!roles.has(d)) roles.set(d, "dopamine");
  roles.set(index, "selected");
  return roles;
}

/** Tubes between a neuron and its strongest partners (at most `max` per direction,
 *  and at most DOPAMINE_LINKS dopamine partners), thicker for more synapses. Neurons
 *  without a position are skipped. */
export function neuronLinks(index: number, c: NeuronConnections, anchor: (i: number) => Vec3 | null,
                            max = 60): Link[] {
  const self = anchor(index);
  if (!self) return [];
  const shown = [...c.inputs.slice(0, max), ...c.outputs.slice(0, max)];
  const top = Math.max(1, ...shown.map((p) => p.synapses));
  const links: Link[] = [];
  for (const p of c.inputs.slice(0, max)) {
    const a = anchor(p.index);
    if (a) links.push({ from: a, to: self, weight: p.synapses / top, role: "input" });
  }
  for (const p of c.outputs.slice(0, max)) {
    const a = anchor(p.index);
    if (a) links.push({ from: self, to: a, weight: p.synapses / top, role: "output" });
  }
  for (const m of c.dopamine_to.slice(0, Math.min(max, DOPAMINE_LINKS))) {
    const a = anchor(m);
    if (a) links.push({ from: self, to: a, weight: 0.3, role: "dopamine" });
  }
  for (const d of c.dopamine_from.slice(0, Math.min(max, DOPAMINE_LINKS))) {
    const a = anchor(d);
    if (a) links.push({ from: a, to: self, weight: 0.3, role: "dopamine" });
  }
  return links;
}

/** Centre of each group's neurons in each hemisphere (scene x < 0 / > 0), keyed "GROUP|side". */
export function groupCentres(groups: string[], anchor: (i: number) => Vec3 | null): Map<string, Vec3> {
  const sums = new Map<string, [number, number, number, number]>();
  groups.forEach((g, i) => {
    const a = anchor(i);
    if (!a) return;
    const key = `${g}|${a[0] < 0 ? "left" : "right"}`;
    const s = sums.get(key) ?? [0, 0, 0, 0];
    s[0] += a[0]; s[1] += a[1]; s[2] += a[2]; s[3] += 1;
    sums.set(key, s);
  });
  const out = new Map<string, Vec3>();
  for (const [k, [x, y, z, n]] of sums) out.set(k, [x / n, y / n, z / n]);
  return out;
}

/** A group's connections to other groups, split by direction (largest first). */
export function groupPartners(group: string, rows: GroupConnection[]): { inputs: GroupConnection[];
                                                                           outputs: GroupConnection[] } {
  const strength = (r: GroupConnection) => r.synapses || r.connections;
  const by = (a: GroupConnection, b: GroupConnection) => strength(b) - strength(a);
  return {
    inputs: rows.filter((r) => r.post === group).sort(by),
    outputs: rows.filter((r) => r.pre === group).sort(by),
  };
}

/** Roles for a selected group: its members, and the neurons of partner groups. */
export function groupRoles(group: string, groups: string[], rows: GroupConnection[]): Map<number, Role> {
  const { inputs, outputs } = groupPartners(group, rows);
  const role = new Map<string, Role>();
  for (const r of inputs) role.set(r.pre, r.sign === "dopamine" ? "dopamine" : "input");
  for (const r of outputs) {
    const was = role.get(r.post);
    role.set(r.post, r.sign === "dopamine" ? "dopamine" : was === "input" ? "both" : "output");
  }
  role.set(group, "member");
  const out = new Map<number, Role>();
  groups.forEach((g, i) => {
    const r = role.get(g);
    if (r) out.set(i, r);
  });
  return out;
}

/** Tubes between a group's centre and its partner groups' centres, in each hemisphere. */
export function groupLinks(group: string, rows: GroupConnection[], centres: Map<string, Vec3>): Link[] {
  const { inputs, outputs } = groupPartners(group, rows);
  const strength = (r: GroupConnection) => r.synapses || r.connections;
  const top = Math.max(1, ...[...inputs, ...outputs].map(strength));
  const links: Link[] = [];
  for (const side of ["left", "right"]) {
    const self = centres.get(`${group}|${side}`);
    if (!self) continue;
    for (const r of [...inputs, ...outputs]) {
      if (r.pre === r.post) continue;                   // within the group (e.g. KC -> KC)
      const incoming = r.post === group;
      const other = centres.get(`${incoming ? r.pre : r.post}|${side}`);
      if (!other) continue;
      links.push({ from: incoming ? other : self, to: incoming ? self : other, weight: strength(r) / top,
                   role: r.sign === "dopamine" ? "dopamine" : incoming ? "input" : "output" });
    }
  }
  return links;
}
