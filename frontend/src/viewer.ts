// viewer.ts — the 3D scene: brain regions, neurons, and connections.
//
// Layers, back to front:
//   brain regions   translucent meshes of the neuropils (FlyWire circuits only); the
//                   odour pathway (antennal lobe, mushroom body, lateral horn) stronger
//   neurons         each neuron's real shape as lines (when the circuit has a morphology
//                   file), otherwise one dot per neuron
//   connections     tubes from a selected neuron (or group) to its partners
//
// Neuron colors change every frame (spikes flash white). With 1.8 million line points
// that can't be done per vertex, so each line point stores only its neuron's index,
// and the shader looks up that neuron's color in a small texture (one texel per
// neuron) that is rewritten every frame.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";

import { groupColor, lerp, ROLE_COLORS, SILENCED, weightColor, writeActivityColor, type RGB, type Role } from "./colors";
import { applyFrame, toScene, type SceneFrame } from "./geometry";
import { shapeIndex, type Morphology } from "./morphology";
import { pickNearest, type PickTier } from "./picking";
import type { BrainRegions, MbonWeight, NeuronTable } from "./types";

/** Dot size per group, in scene units (the brain spans ~2 units). */
const POINT_SIZE: Record<string, number> = {
  ORN: 0.014, ALPN: 0.024, KC: 0.016, APL: 0.09, DPM: 0.07, MBON: 0.055, DAN_PPL1: 0.04, DAN_PAM: 0.035,
};
const DEFAULT_SIZE = 0.02;

/** Opacity of each group's shape at rest. Overlapping lines build up toward their
 *  color, so the 5,000 Kenyon cells stay faint and the few large cells strong. */
const LINE_ALPHA: Record<string, number> = {
  ORN: 0.05, ALLN: 0.03, ALPN: 0.12, KC: 0.05, APL: 0.03, DPM: 0.05, MBON: 0.16, DAN_PPL1: 0.1, DAN_PAM: 0.05,
};
const DEFAULT_ALPHA = 0.2;
const DIMMED = 0.12;            // opacity factor of neurons outside the focus
const BACKGROUND = 0x070a12;


export type { Role } from "./colors";

/** A line between two places, drawn as a tube. */
export interface Link {
  from: [number, number, number];   // scene coordinates
  to: [number, number, number];
  weight: number;                   // 0..1: tube thickness
  role: "input" | "output" | "dopamine";
}

const REGION_COLORS: Record<string, number> = {
  AL: 0x2dd4bf, MB_CA: 0xc4b5fd, MB_PED: 0xc4b5fd, MB_VL: 0xc4b5fd, MB_ML: 0xc4b5fd, LH: 0x60a5fa,
};
const REGION_GREY = 0x64748b;

interface GroupCloud {
  name: string;
  indices: Int32Array;           // global neuron index of each point
  colors: Float32Array;          // rgb per point, rewritten each frame
  colorAttr: THREE.BufferAttribute;
  points: THREE.Points;
}

/** A soft round sprite so points render as dots, not squares. */
function dotTexture(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.6, "rgba(255,255,255,0.9)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** Lines whose color and opacity come from the neuron state texture. */
function shapeMaterial(state: THREE.DataTexture, width: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: { state: { value: state }, stateWidth: { value: width } },
    vertexShader: /* glsl */ `
      attribute float neuron;
      uniform sampler2D state;
      uniform int stateWidth;
      varying vec4 vColor;
      void main() {
        int i = int(neuron + 0.5);
        vColor = texelFetch(state, ivec2(i % stateWidth, i / stateWidth), 0);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        if (vColor.a < 0.002) gl_Position = vec4(0.0, 0.0, 2.0, 1.0);   // hidden: outside the view
      }`,
    fragmentShader: /* glsl */ `
      varying vec4 vColor;
      void main() { gl_FragColor = vColor; }`,
    transparent: true,
    depthWrite: false,
  });
}

/** Glass-like surface: faint face-on, brighter at the silhouette, so a region reads
 *  as an outline without hiding what's inside. */
function regionMaterial(color: number, opacity: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: { color: { value: new THREE.Color(color) }, opacity: { value: opacity } },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vView;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color;
      uniform float opacity;
      varying vec3 vNormal;
      varying vec3 vView;
      void main() {
        float rim = 1.0 - abs(dot(normalize(vNormal), normalize(vView)));
        gl_FragColor = vec4(color, opacity * (0.12 + 0.88 * pow(rim, 2.5)));
      }`,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

export class BrainViewer {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly labels: CSS2DRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly resizeObserver: ResizeObserver;
  private readonly texture: THREE.Texture;
  private readonly n: number;

  // neuron state
  private readonly groupIndex: Int32Array;             // neuron -> index into groupNames
  private readonly groupNames: string[];
  private readonly groupVisible: boolean[];
  private readonly base: RGB[];                         // resting color per neuron
  private weights: MbonWeight[] | null = null;
  private silenced = new Set<number>();
  private focus: Map<number, Role> | null = null;
  private readonly positions: Float32Array;             // anchor (soma) per neuron, scene coordinates
  private readonly valid: Uint8Array;
  private readonly stateData: Uint8Array;               // rgba per neuron, read by the line shader
  private readonly state: THREE.DataTexture;
  private readonly stateWidth = 256;

  // layers
  private readonly clouds: GroupCloud[] = [];
  private readonly shapes: THREE.LineSegments[] = [];   // one per group
  private hasShape = new Uint8Array(0);                 // neuron drawn as a shape
  private showShapes = true;
  private readonly regionGroup = new THREE.Group();
  private readonly labelGroup = new THREE.Group();
  private readonly linkGroup = new THREE.Group();
  private readonly marker: THREE.Mesh;
  private home = { target: new THREE.Vector3(), size: [2, 2, 2] };   // the reset view: what to fit

  // picking: every drawn point and the neuron it belongs to
  private pickPoints = new Float32Array(0);
  private pickOwner = new Int32Array(0);
  private shapePick: { points: Float32Array; owner: Int32Array } | null = null;

  constructor(
    private readonly container: HTMLElement,
    private readonly table: NeuronTable,
    private readonly frame: SceneFrame | null = null,
  ) {
    this.n = table.count;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "region-labels";
    container.appendChild(this.labels.domElement);

    this.scene.background = new THREE.Color(BACKGROUND);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    this.groupNames = [...new Set(table.group)];
    const code = new Map(this.groupNames.map((g, k) => [g, k]));
    this.groupIndex = Int32Array.from(table.group, (g) => code.get(g)!);
    this.groupVisible = this.groupNames.map(() => true);
    this.base = table.group.map((g) => groupColor(g));

    const scene = toScene(table, frame ?? undefined);
    this.positions = scene.positions;
    this.valid = scene.valid;
    this.stateData = new Uint8Array(this.stateWidth * Math.ceil(Math.max(1, this.n) / this.stateWidth) * 4);
    this.state = new THREE.DataTexture(this.stateData, this.stateWidth, this.stateData.length / 4 / this.stateWidth,
                                       THREE.RGBAFormat, THREE.UnsignedByteType);
    this.state.magFilter = this.state.minFilter = THREE.NearestFilter;
    this.state.needsUpdate = true;

    this.texture = dotTexture();
    this.scene.add(this.regionGroup, this.labelGroup, this.linkGroup);
    this.marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12),
                                 new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true,
                                                               opacity: 0.6, depthTest: false }));
    this.marker.visible = false;
    this.marker.renderOrder = 10;
    this.scene.add(this.marker);
    this.buildClouds();
    this.fitHome();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.resetView();
  }

  // ------------------------------------------------------------------ building

  /** One dot per neuron that has a position and no shape. */
  private buildClouds(): void {
    for (const c of this.clouds) {
      this.scene.remove(c.points);
      c.points.geometry.dispose();
      (c.points.material as THREE.Material).dispose();
    }
    this.clouds.length = 0;
    const byGroup = new Map<string, number[]>();
    for (let i = 0; i < this.n; i++) {
      if (!this.valid[i] || (this.showShapes && this.hasShape[i])) continue;
      const g = this.table.group[i]!;
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g)!.push(i);
    }
    for (const [name, list] of byGroup) {
      const indices = Int32Array.from(list);
      const pos = new Float32Array(indices.length * 3);
      indices.forEach((i, k) => pos.set(this.positions.subarray(i * 3, i * 3 + 3), k * 3));
      const colors = new Float32Array(indices.length * 3);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const colorAttr = new THREE.BufferAttribute(colors, 3);
      colorAttr.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("color", colorAttr);
      const material = new THREE.PointsMaterial({
        size: POINT_SIZE[name] ?? DEFAULT_SIZE, map: this.texture, vertexColors: true, transparent: true,
        alphaTest: 0.05, depthWrite: false, sizeAttenuation: true,
      });
      const points = new THREE.Points(geometry, material);
      points.name = name;
      points.visible = this.groupVisible[this.groupNames.indexOf(name)] ?? true;
      this.scene.add(points);
      this.clouds.push({ name, indices, colors, colorAttr, points });
    }
    this.rebuildPicking();
  }

  /** Brain region meshes. Call before or after the neurons; the frame decides the fit. */
  setRegions(regions: BrainRegions): void {
    if (!this.frame) return;                       // regions need FlyWire coordinates
    this.regionGroup.clear();
    this.labelGroup.clear();
    for (const r of regions.regions) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(applyFrame(this.frame, r.vertices), 3));
      geometry.setIndex(r.triangles);
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, regionMaterial(REGION_COLORS[r.region] ?? REGION_GREY,
                                                             r.olfactory ? 0.55 : 0.16));
      mesh.renderOrder = r.olfactory ? 1 : 0;
      mesh.name = r.name;
      this.regionGroup.add(mesh);
      // label the odour pathway, on one side (the other side mirrors it)
      if (r.olfactory && r.side === "right") {
        geometry.computeBoundingBox();
        const center = geometry.boundingBox!.getCenter(new THREE.Vector3());
        const div = document.createElement("div");
        div.className = "region-label";
        div.textContent = r.label.replace("mushroom body ", "MB ");
        div.title = r.label;
        const label = new CSS2DObject(div);
        // at the region's outer edge, the label extending outward, so labels of
        // neighbouring regions overlap less
        const box = geometry.boundingBox!;
        const outer = Math.abs(box.max.x) > Math.abs(box.min.x) ? box.max.x : box.min.x;
        label.position.set(outer, center.y, center.z);
        label.center.set(outer >= 0 ? 0 : 1, 0.5);
        this.labelGroup.add(label);
      }
    }
  }

  /** Draw neurons as their real shapes; neurons without one stay dots. */
  setMorphology(m: Morphology): void {
    if (!this.frame) return;
    for (const s of this.shapes) {
      this.scene.remove(s);
      s.geometry.dispose();
    }
    this.shapes.length = 0;
    const shapeOf = shapeIndex(m, this.table.flywire_id ?? this.table.root_id);
    // Units sharing one FlyWire neuron (regional APL) draw its shape once, as the first unit.
    const drawn = new Set<number>();
    this.hasShape = new Uint8Array(this.n);
    const scenePos = applyFrame(this.frame, m.positions);
    const material = shapeMaterial(this.state, this.stateWidth);
    const pickPos: number[] = [];
    const pickOwn: number[] = [];

    for (let g = 0; g < this.groupNames.length; g++) {
      let vertices = 0;
      let segments = 0;                            // one per vertex with a parent
      const members: number[] = [];
      for (let i = 0; i < this.n; i++) {
        const k = shapeOf[i]!;
        if (this.groupIndex[i] !== g || k < 0) continue;
        this.hasShape[i] = 1;
        if (drawn.has(k)) continue;
        drawn.add(k);
        members.push(i);
        vertices += m.count[k]!;
        for (let v = m.start[k]!; v < m.start[k]! + m.count[k]!; v++) if (m.parent[v]! >= 0) segments++;
      }
      if (!members.length) continue;
      const pos = new Float32Array(vertices * 3);
      const owner = new Float32Array(vertices);
      const index = vertices > 65535 ? new Uint32Array(segments * 2) : new Uint16Array(segments * 2);
      let at = 0;
      let e = 0;
      for (const i of members) {
        const k = shapeOf[i]!;
        const s = m.start[k]!, c = m.count[k]!;
        pos.set(scenePos.subarray(s * 3, (s + c) * 3), at * 3);
        owner.fill(i, at, at + c);
        for (let v = 0; v < c; v++) {
          const p = m.parent[s + v]!;
          if (p >= 0) {
            index[e++] = at + v;
            index[e++] = at + (p - s);
          }
          // picking uses every other point: plenty for a cursor a few pixels wide
          if ((v & 1) === 0) {
            pickPos.push(scenePos[(s + v) * 3]!, scenePos[(s + v) * 3 + 1]!, scenePos[(s + v) * 3 + 2]!);
            pickOwn.push(i);
          }
        }
        at += c;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geometry.setAttribute("neuron", new THREE.BufferAttribute(owner, 1));
      geometry.setIndex(new THREE.BufferAttribute(index, 1));
      const lines = new THREE.LineSegments(geometry, material);
      lines.name = this.groupNames[g]!;
      lines.frustumCulled = false;
      // Kenyon cells last: their axons make the mushroom body's shape, and the dense
      // dopamine and output neuron arbors in the lobes would otherwise cover them
      lines.renderOrder = this.groupNames[g] === "KC" ? 3 : 2;
      lines.visible = this.showShapes && this.groupVisible[g]!;
      this.scene.add(lines);
      this.shapes.push(lines);
    }
    this.shapePick = { points: Float32Array.from(pickPos), owner: Int32Array.from(pickOwn) };
    this.buildClouds();
  }

  /** Points used for picking: shape points (if shown) plus every dot. */
  private rebuildPicking(): void {
    const dotOwners = this.clouds.flatMap((c) => Array.from(c.indices));
    const shapes = this.showShapes && this.shapePick ? this.shapePick : { points: new Float32Array(0),
                                                                          owner: new Int32Array(0) };
    const points = new Float32Array(shapes.points.length + dotOwners.length * 3);
    points.set(shapes.points);
    dotOwners.forEach((i, k) => points.set(this.positions.subarray(i * 3, i * 3 + 3), shapes.points.length + k * 3));
    const owner = new Int32Array(shapes.owner.length + dotOwners.length);
    owner.set(shapes.owner);
    owner.set(dotOwners, shapes.owner.length);
    this.pickPoints = points;
    this.pickOwner = owner;
  }

  get hasMorphology(): boolean {
    return this.shapes.length > 0;
  }

  get hasRegions(): boolean {
    return this.regionGroup.children.length > 0;
  }

  // ------------------------------------------------------------------ display options

  get groups(): string[] {
    return [...this.groupNames];
  }

  setGroupVisible(name: string, visible: boolean): void {
    const g = this.groupNames.indexOf(name);
    if (g < 0) return;
    this.groupVisible[g] = visible;
    for (const c of this.clouds) if (c.name === name) c.points.visible = visible;
    for (const s of this.shapes) if (s.name === name) s.visible = visible && this.showShapes;
  }

  setRegionsVisible(visible: boolean): void {
    this.regionGroup.visible = visible;
  }

  setLabelsVisible(visible: boolean): void {
    this.labelGroup.visible = visible;
    this.labels.domElement.hidden = !visible;
  }

  /** Shapes (true) or one dot per neuron (false). */
  setShapesVisible(visible: boolean): void {
    if (visible === this.showShapes) return;
    this.showShapes = visible;
    this.shapes.forEach((s) => {
      s.visible = visible && this.groupVisible[this.groupNames.indexOf(s.name)]!;
    });
    this.buildClouds();
  }

  /** Color MBONs by how much their KC inputs weakened; null restores normal colors. */
  setMbonWeights(weights: MbonWeight[] | null): void {
    this.weights = weights;
    this.recolor();
  }

  /** Grey out lesioned neurons (they never fire, so they never light up). */
  setSilenced(neurons: number[]): void {
    this.silenced = new Set(neurons);
    this.recolor();
  }

  /** Highlight some neurons, each in its role's color, and dim the rest; null ends the focus. */
  setFocus(roles: Map<number, Role> | null): void {
    this.focus = roles && roles.size ? roles : null;
  }

  /** Tubes for connections (replacing any shown). */
  setLinks(links: Link[]): void {
    for (const child of [...this.linkGroup.children]) {
      const mesh = child as THREE.Mesh;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    }
    this.linkGroup.clear();
    for (const l of links) {
      const a = new THREE.Vector3(...l.from);
      const b = new THREE.Vector3(...l.to);
      const length = a.distanceTo(b);
      if (length < 1e-4) continue;
      // bow the tube sideways (up in the view) so lines between nearby cells don't overlap
      const mid = a.clone().add(b).multiplyScalar(0.5).add(new THREE.Vector3(0, 0.18 * length, 0));
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      // tube radius in scene units (the brain is 2 units, ~800 µm, wide): 0.3 to 1.6 µm
      const radius = 0.0006 + 0.0026 * Math.sqrt(Math.max(0, Math.min(1, l.weight)));
      const material = new THREE.MeshBasicMaterial({ color: new THREE.Color(...ROLE_COLORS[l.role]),
                                                     transparent: true, opacity: 0.65, depthWrite: false });
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, radius, 6, false), material);
      tube.renderOrder = 5;
      this.linkGroup.add(tube);
      // an arrowhead near the receiving end shows the direction
      const tip = curve.getPoint(0.92);
      const dir = curve.getTangent(0.92);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(radius * 2.6, radius * 7, 8), material);
      cone.position.copy(tip);
      cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      cone.renderOrder = 5;
      this.linkGroup.add(cone);
    }
  }

  /** Anchor (cell body) of a neuron in scene coordinates, or null if unknown. */
  anchor(index: number): [number, number, number] | null {
    if (!this.valid[index]) return null;
    return [this.positions[index * 3]!, this.positions[index * 3 + 1]!, this.positions[index * 3 + 2]!];
  }

  /** Mark a neuron's cell body (null: no marker). */
  select(index: number | null): void {
    const a = index === null ? null : this.anchor(index);
    if (!a) {
      this.marker.visible = false;
      return;
    }
    this.marker.position.set(...a);
    this.marker.scale.setScalar(0.007);
    this.marker.visible = true;
  }

  // ------------------------------------------------------------------ picking

  /** Call `onSelect` with the neuron under a click (null: empty space). Drags,
   *  which rotate the view, don't select. */
  onPick(onSelect: (index: number | null, side: "left" | "right") => void): void {
    const el = this.renderer.domElement;
    let down: { x: number; y: number } | null = null;
    el.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      down = null;
      const rect = el.getBoundingClientRect();     // which half of the view was clicked
      onSelect(this.pick(e.clientX, e.clientY), e.clientX - rect.left < rect.width / 2 ? "left" : "right");
    });
  }

  /** The visible neuron nearest a screen point (within 6 px), or null. */
  pick(clientX: number, clientY: number): number | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.camera.updateMatrixWorld();
    const vp = new THREE.Matrix4().multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse);
    return pickNearest(this.pickPoints, this.pickOwner, vp.elements, rect.width, rect.height,
                       clientX - rect.left, clientY - rect.top, 6, (i) => this.tier(i));
  }

  private tier(i: number): PickTier {
    if (!this.groupVisible[this.groupIndex[i]!]) return 0;
    return this.focus ? (this.focus.has(i) ? 2 : 1) : 1;
  }

  // ------------------------------------------------------------------ per frame

  /** Resting colors: silenced grey, then MBON learning colors, else the group color. */
  private recolor(): void {
    const ratio = new Map((this.weights ?? []).map((w) => [w.index, w.weight_ratio]));
    for (let i = 0; i < this.n; i++) {
      const r = ratio.get(i);
      this.base[i] = this.silenced.has(i) ? SILENCED : r !== undefined ? weightColor(r) : groupColor(this.table.group[i]!);
    }
  }

  /** Apply per-neuron activity (0..1, indexed by neuron) to the neurons' colors. */
  update(activity: Float32Array): void {
    const d = this.stateData;
    for (let i = 0; i < this.n; i++) {
      const g = this.groupIndex[i]!;
      const a = Math.min(1, Math.max(0, activity[i] ?? 0));
      if (!this.groupVisible[g]) {
        d[i * 4 + 3] = 0;
        continue;
      }
      const role = this.focus?.get(i);
      let color = this.base[i]!;
      let alpha = LINE_ALPHA[this.groupNames[g]!] ?? DEFAULT_ALPHA;
      if (role) {
        if (role !== "member") color = lerp(color, ROLE_COLORS[role], 0.8);
        // brighter than at rest, but large groups (5,000 Kenyon cells) stay see-through
        alpha = role === "selected" ? 1 : Math.min(0.9, Math.max(0.2, alpha * 4));
      } else if (this.focus) {
        alpha *= DIMMED;
      }
      // a spike: toward white and fully opaque, fading with the activity trace
      d[i * 4] = Math.round(255 * (color[0] + (1 - color[0]) * a));
      d[i * 4 + 1] = Math.round(255 * (color[1] + (1 - color[1]) * a));
      d[i * 4 + 2] = Math.round(255 * (color[2] + (1 - color[2]) * a));
      d[i * 4 + 3] = Math.round(255 * (alpha + (1 - alpha) * a));
    }
    this.state.needsUpdate = true;

    for (const c of this.clouds) {
      if (!c.points.visible) continue;
      const { indices, colors } = c;
      for (let k = 0; k < indices.length; k++) {
        const i = indices[k]!;
        const role = this.focus?.get(i);
        const color = role && role !== "member" ? lerp(this.base[i]!, ROLE_COLORS[role], 0.8) : this.base[i]!;
        writeActivityColor(color, activity[i] ?? 0, colors, k * 3);
        if (this.focus && !role) for (let j = 0; j < 3; j++) colors[k * 3 + j]! *= 0.3;
      }
      c.colorAttr.needsUpdate = true;
    }
  }

  render(): void {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    if (this.labelGroup.visible && this.labelGroup.children.length) this.labels.render(this.scene, this.camera);
  }

  /** The reset view: looking at the neurons from the front, all of them in view. */
  private fitHome(): void {
    const lo = [Infinity, Infinity, Infinity];
    const hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < this.n; i++) {
      if (!this.valid[i]) continue;
      for (let a = 0; a < 3; a++) {
        lo[a] = Math.min(lo[a]!, this.positions[i * 3 + a]!);
        hi[a] = Math.max(hi[a]!, this.positions[i * 3 + a]!);
      }
    }
    if (!Number.isFinite(lo[0]!)) return;
    this.home.target.set((lo[0]! + hi[0]!) / 2, (lo[1]! + hi[1]!) / 2, (lo[2]! + hi[2]!) / 2);
    this.home.size = [hi[0]! - lo[0]!, hi[1]! - lo[1]!, hi[2]! - lo[2]!];
  }

  resetView(): void {
    // far enough that the neurons' width fits the view's width and their height its height
    const [w, h, d] = this.home.size as [number, number, number];
    const tan = Math.tan((this.camera.fov * Math.PI) / 360);
    const distance = Math.max(0.5, 0.6 * Math.max(h / tan, w / (tan * this.camera.aspect)) + d / 2);
    const t = this.home.target;
    this.camera.position.set(t.x, t.y + 0.08 * distance, t.z + distance);
    this.controls.target.copy(t);
    this.controls.update();
  }

  private resize(): void {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h, false);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  dispose(): void {
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.setLinks([]);
    for (const c of this.clouds) {
      c.points.geometry.dispose();
      (c.points.material as THREE.Material).dispose();
    }
    for (const s of this.shapes) s.geometry.dispose();
    (this.shapes[0]?.material as THREE.Material | undefined)?.dispose();
    this.regionGroup.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        (o.material as THREE.Material).dispose();
      }
    });
    this.state.dispose();
    this.texture.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }
}
