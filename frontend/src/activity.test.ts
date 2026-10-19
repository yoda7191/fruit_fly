import { describe, expect, it } from "vitest";

import { ActivityBuffer } from "./activity";

describe("ActivityBuffer", () => {
  it("lights a neuron on spike and fades exponentially", () => {
    const a = new ActivityBuffer(3, 100);
    a.spike(1);
    expect(Array.from(a.values)).toEqual([0, 1, 0]);
    a.decay(100);
    expect(a.values[1]).toBeCloseTo(Math.exp(-1), 5);
  });

  it("snaps tiny values to zero, ignores bad indices, resets", () => {
    const a = new ActivityBuffer(2, 10);
    a.spike(0);
    a.spike(-1);
    a.spike(2);
    a.decay(1000);
    expect(a.values[0]).toBe(0);
    a.spike(1);
    a.reset();
    expect(Array.from(a.values)).toEqual([0, 0]);
    a.decay(-5);                                   // no-op
  });
});