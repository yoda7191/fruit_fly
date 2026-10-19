// colors.ts — colors for neuron groups, learning, and activity.

export type RGB = [number, number, number];

export function hexToRgb(hex: number): RGB {
  return [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255];
}

export function cssColor([r, g, b]: RGB): string {
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}

/** Linear blend; exact at t = 0 (a) and t = 1 (b). */
export function lerp(a: RGB, b: RGB, t: number): RGB {
  const s = 1 - t;
  return [a[0] * s + b[0] * t, a[1] * s + b[1] * t, a[2] * s + b[2] * t];
}

/** One color per neuron group, following the signal path (input -> output -> teaching). */
export const GROUP_COLORS: Record<string, RGB> = {
  ORN: hexToRgb(0x2dd4bf),        // teal: receptor neurons
  ALLN: hexToRgb(0x818cf8),       // indigo: antennal lobe local neurons
  ALPN: hexToRgb(0x60a5fa),       // blue: projection neurons
  KC: hexToRgb(0x5b6b85),         // slate: Kenyon cells (dark, so their sparse spikes stand out)
  APL: hexToRgb(0xf97316),        // orange: global inhibition
  DPM: hexToRgb(0xc084fc),        // violet
  MBON: hexToRgb(0xfacc15),       // yellow: output neurons
  DAN_PPL1: hexToRgb(0xef4444),   // red: punishment dopamine
  DAN_PAM: hexToRgb(0x22c55e),    // green: reward dopamine
};

const FALLBACK: RGB = hexToRgb(0x9ca3af);

export function groupColor(group: string): RGB {
  return GROUP_COLORS[group] ?? FALLBACK;
}

/** Lesioned (silenced) neurons: a dark grey that never lights up. */
export const SILENCED: RGB = [0.16, 0.18, 0.22];

/** Brightness of resting neurons, so spikes (-> white) stand out. */
export const REST_BRIGHTNESS = 0.45;

const DEPRESSED: RGB = hexToRgb(0x7c3aed);  // purple: synapses fully weakened

/**
 * MBON color from its mean KC-input weight ratio (after / before training):
 * 1 = unchanged (normal MBON yellow), 0 = fully depressed (purple).
 */
export function weightColor(ratio: number): RGB {
  const t = Math.min(1, Math.max(0, ratio));
  return lerp(DEPRESSED, GROUP_COLORS.MBON!, t);
}

/**
 * Write a point's display color into out[offset..offset+2]:
 * resting color dimmed, moving toward white as activity goes to 1.
 */
export function writeActivityColor(base: RGB, activity: number, out: Float32Array, offset: number): void {
  const a = Math.min(1, Math.max(0, activity));
  for (let k = 0; k < 3; k++) {
    const rest = base[k]! * REST_BRIGHTNESS;
    out[offset + k] = rest + (1 - rest) * a;
  }
}
/** A neuron's role while a neuron or group is in focus (the connection explorer). */
export type Role = "selected" | "input" | "output" | "both" | "dopamine" | "member";

/** Colors of those roles ("member" keeps the group color). */
export const ROLE_COLORS: Record<Exclude<Role, "member">, RGB> = {
  selected: [1, 1, 1],
  input: hexToRgb(0x38bdf8),    // sky blue: sends to the selected neuron
  output: hexToRgb(0xfb923c),   // orange: receives from it
  both: hexToRgb(0xe879f9),     // pink: both directions
  dopamine: hexToRgb(0xa3e635), // lime: dopamine coupling (DAN -> MBON)
};
