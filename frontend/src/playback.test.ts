import { describe, expect, it, vi } from "vitest";

import { lowerBound, SpikePlayer, type SpikeFetcher } from "./playback";
import type { SpikeWindow } from "./types";

/** One spike every 10 ms: neuron = time / 10, times 0, 10, 20, ... */
function regularSpikes(durationMs: number): SpikeFetcher {
  return async (t0, t1) => {
    const times: number[] = [];
    for (let t = Math.ceil(t0 / 10) * 10; t < Math.min(t1, durationMs); t += 10) times.push(t);
    return window(t0, t1, times.map((t) => t / 10), times);
  };
}

function window(t0: number, t1: number, neurons: number[], times: number[], truncated = false): SpikeWindow {
  return { t0_ms: t0, t1_ms: t1, count: neurons.length, truncated, neurons, times_ms: times };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("lowerBound", () => {
  it("finds the first index >= value", () => {
    const a = Float64Array.from([1, 3, 3, 5]);
    expect(lowerBound(a, 0)).toBe(0);
    expect(lowerBound(a, 3)).toBe(1);
    expect(lowerBound(a, 4)).toBe(3);
    expect(lowerBound(a, 9)).toBe(4);
    expect(lowerBound(new Float64Array(0), 1)).toBe(0);
  });
});

describe("SpikePlayer", () => {
  it("emits every spike exactly once across chunk boundaries", async () => {
    const player = new SpikePlayer(2000, regularSpikes(2000), { chunkMs: 300 });
    await flush();
    player.play();
    const seen: number[] = [];
    for (let i = 0; i < 400 && !player.finished; i++) {
      player.advance(7, (n) => seen.push(n));   // odd step size on purpose
      await flush();
    }
    expect(player.finished).toBe(true);
    expect(player.playing).toBe(false);
    expect(seen).toEqual(Array.from({ length: 200 }, (_, i) => i));
  });

  it("buffers instead of skipping when data has not arrived", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const inner = regularSpikes(1000);
    const player = new SpikePlayer(1000, async (t0, t1, s) => {
      await gate;
      return inner(t0, t1, s);
    });
    player.play();
    const seen: number[] = [];
    expect(player.advance(50, (n) => seen.push(n))).toBe(0);
    expect(player.buffering).toBe(true);
    expect(player.time).toBe(0);
    release();
    await flush();
    player.advance(50, (n) => seen.push(n));
    expect(player.buffering).toBe(false);
    expect(seen).toEqual([0, 1, 2, 3, 4]);          // t = 0..40, none skipped
  });

  it("applies speed and emits nothing while paused", async () => {
    const player = new SpikePlayer(1000, regularSpikes(1000));
    await flush();
    const seen: number[] = [];
    player.advance(100, (n) => seen.push(n));
    expect(seen).toEqual([]);
    player.speed = 2;
    player.play();
    player.advance(50, (n) => seen.push(n));        // 100 ms of simulated time
    expect(player.time).toBe(100);
    expect(seen).toHaveLength(10);
  });

  it("seeks, clamps, and restarts from zero after finishing", async () => {
    const player = new SpikePlayer(1000, regularSpikes(1000));
    player.seek(-50);
    expect(player.time).toBe(0);
    player.seek(5000);
    expect(player.finished).toBe(true);
    player.play();
    expect(player.time).toBe(0);
    player.seek(600);
    await flush();
    const seen: number[] = [];
    player.advance(25, (n) => seen.push(n));
    expect(seen).toEqual([60, 61, 62]);
  });

  it("only requests nearby chunks and cancels far ones after a seek", async () => {
    const calls: number[] = [];
    const aborted: number[] = [];
    const fetcher: SpikeFetcher = (t0, _t1, signal) => {
      calls.push(t0);
      signal.addEventListener("abort", () => aborted.push(t0));
      return new Promise(() => {});               // never resolves
    };
    const player = new SpikePlayer(10_000, fetcher, { chunkMs: 500, prefetch: 2 });
    expect(calls).toEqual([0, 500, 1000]);
    player.seek(8000);
    expect(aborted).toEqual([0, 500, 1000]);
    expect(calls.slice(3)).toEqual([8000, 8500, 9000]);
  });

  it("stops and reports fetch errors", async () => {
    const onError = vi.fn();
    const player = new SpikePlayer(1000, async () => { throw new Error("boom"); }, { onError });
    await flush();
    player.play();
    expect(player.playing).toBe(false);
    expect(player.error?.message).toBe("boom");
    expect(onError).toHaveBeenCalledOnce();
    expect(player.advance(100, () => {})).toBe(0);
  });

  it("counts truncated chunks", async () => {
    const player = new SpikePlayer(1000, async (t0, t1) => window(t0, t1, [], [], true), { chunkMs: 500 });
    await flush();
    expect(player.truncatedChunks).toBe(2);
  });

  it("rejects invalid settings", () => {
    const f = regularSpikes(1);
    expect(() => new SpikePlayer(0, f)).toThrow();
    expect(() => new SpikePlayer(100, f, { chunkMs: 0 })).toThrow();
  });
});