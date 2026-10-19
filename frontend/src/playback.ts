// playback.ts — replays a recorded experiment's spikes in (scaled) real time.
//
// Spikes are fetched in fixed windows ("chunks") of simulated time. The player
// keeps the chunk under the playhead plus a few ahead loaded, drops chunks
// far behind, and stalls ("buffering") instead of skipping spikes when data
// hasn't arrived yet. Each animation frame, advance() emits exactly the spikes
// with  previous time <= t < new time.

import type { SpikeWindow } from "./types";

export type SpikeFetcher = (t0Ms: number, t1Ms: number, signal: AbortSignal) => Promise<SpikeWindow>;

export interface PlayerOptions {
  chunkMs?: number;       // simulated ms per fetched window
  prefetch?: number;      // chunks to keep loaded ahead of the playhead
  keepBehind?: number;    // chunks to keep behind it (for small backward seeks)
  onError?: (err: Error) => void;
}

interface Chunk {
  controller: AbortController;
  ready: boolean;
  neurons: Int32Array;
  times: Float64Array;
  truncated: boolean;
}

/** First index k with a[k] >= value (a sorted ascending). */
export function lowerBound(a: Float64Array, value: number): number {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid]! < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export class SpikePlayer {
  /** Current simulated time (ms). */
  time = 0;
  /** Simulated ms per wall-clock ms (1 = real time). */
  speed = 1;
  playing = false;
  buffering = false;
  error: Error | null = null;
  /** Chunks whose window hit the server's max_spikes cap. */
  truncatedChunks = 0;

  private readonly chunks = new Map<number, Chunk>();
  private readonly chunkMs: number;
  private readonly prefetch: number;
  private readonly keepBehind: number;
  private readonly onError?: (err: Error) => void;

  constructor(
    readonly durationMs: number,
    private readonly fetcher: SpikeFetcher,
    opts: PlayerOptions = {},
  ) {
    this.chunkMs = opts.chunkMs ?? 500;
    this.prefetch = opts.prefetch ?? 4;
    this.keepBehind = opts.keepBehind ?? 1;
    this.onError = opts.onError;
    if (!(durationMs > 0)) throw new Error("durationMs must be > 0");
    if (!(this.chunkMs > 0)) throw new Error("chunkMs must be > 0");
    this.ensureChunks();
  }

  get finished(): boolean {
    return this.time >= this.durationMs;
  }

  play(): void {
    if (this.error) return;
    if (this.finished) this.seek(0);
    this.playing = true;
  }

  pause(): void {
    this.playing = false;
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  seek(timeMs: number): void {
    this.time = Math.min(Math.max(0, timeMs), this.durationMs);
    this.ensureChunks();
  }

  /**
   * Move forward by wallDtMs * speed of simulated time, calling onSpike for
   * every spike crossed. Returns the number of spikes emitted.
   */
  advance(wallDtMs: number, onSpike: (neuron: number, timeMs: number) => void): number {
    this.ensureChunks();
    if (!this.playing || this.error || wallDtMs <= 0) return 0;
    if (this.finished) {
      this.playing = false;
      return 0;
    }

    const target = Math.min(this.time + wallDtMs * this.speed, this.durationMs);
    const first = this.chunkIndex(this.time);
    const last = this.chunkIndex(Math.max(this.time, target - 1e-9));
    for (let c = first; c <= last; c++) {
      if (!this.chunks.get(c)?.ready) {
        this.buffering = true;
        return 0;
      }
    }
    this.buffering = false;

    let emitted = 0;
    for (let c = first; c <= last; c++) {
      const chunk = this.chunks.get(c)!;
      const lo = lowerBound(chunk.times, this.time);
      const hi = lowerBound(chunk.times, target);
      for (let k = lo; k < hi; k++) onSpike(chunk.neurons[k]!, chunk.times[k]!);
      emitted += hi - lo;
    }
    this.time = target;
    if (this.finished) this.playing = false;
    this.ensureChunks();
    return emitted;
  }

  /** Abort all pending requests. */
  dispose(): void {
    for (const chunk of this.chunks.values()) chunk.controller.abort();
    this.chunks.clear();
    this.playing = false;
  }

  // ------------------------------------------------------------------ internals

  private chunkIndex(timeMs: number): number {
    return Math.floor(timeMs / this.chunkMs);
  }

  private ensureChunks(): void {
    if (this.error) return;
    const current = this.chunkIndex(Math.min(this.time, this.durationMs - 1e-9));
    const lo = current - this.keepBehind;
    const hi = current + this.prefetch;

    for (const [c, chunk] of this.chunks) {
      if (c < lo || c > hi) {
        chunk.controller.abort();
        this.chunks.delete(c);
      }
    }
    for (let c = Math.max(0, current); c <= hi; c++) {
      if (c * this.chunkMs >= this.durationMs) break;
      if (!this.chunks.has(c)) this.load(c);
    }
  }

  private load(c: number): void {
    const chunk: Chunk = {
      controller: new AbortController(),
      ready: false,
      neurons: new Int32Array(0),
      times: new Float64Array(0),
      truncated: false,
    };
    this.chunks.set(c, chunk);
    const t0 = c * this.chunkMs;
    this.fetcher(t0, t0 + this.chunkMs, chunk.controller.signal).then(
      (w) => {
        if (this.chunks.get(c) !== chunk) return;          // evicted meanwhile
        chunk.neurons = Int32Array.from(w.neurons);
        chunk.times = Float64Array.from(w.times_ms);
        chunk.truncated = w.truncated;
        if (w.truncated) this.truncatedChunks++;
        chunk.ready = true;
      },
      (err: unknown) => {
        if (chunk.controller.signal.aborted) return;        // we cancelled it
        if (this.error) return;                             // already reported once
        this.error = err instanceof Error ? err : new Error(String(err));
        this.playing = false;
        this.onError?.(this.error);
      },
    );
  }
}