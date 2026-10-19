// activity.ts — how brightly each neuron is "lit" right now.
// A spike sets its neuron to 1; brightness then fades exponentially in
// wall-clock time, so flashes stay visible at any playback speed.

export class ActivityBuffer {
  readonly values: Float32Array;

  constructor(
    readonly size: number,
    public tauMs = 150,
  ) {
    this.values = new Float32Array(size);
  }

  spike(neuron: number): void {
    if (neuron >= 0 && neuron < this.size) this.values[neuron] = 1;
  }

  decay(wallDtMs: number): void {
    if (wallDtMs <= 0) return;
    const f = Math.exp(-wallDtMs / this.tauMs);
    const v = this.values;
    for (let i = 0; i < v.length; i++) {
      const x = v[i]!;
      if (x !== 0) v[i] = x * f < 1e-3 ? 0 : x * f;
    }
  }

  reset(): void {
    this.values.fill(0);
  }
}