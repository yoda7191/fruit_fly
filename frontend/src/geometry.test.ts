import { describe, expect, it } from "vitest";

import { cssColor, groupColor, hexToRgb, REST_BRIGHTNESS, weightColor, writeActivityColor } from "./colors";

describe("colors", () => {
  it("converts hex", () => {
    expect(hexToRgb(0xff8000)).toEqual([1, 128 / 255, 0]);
    expect(cssColor([1, 0.5, 0])).toBe("rgb(255, 128, 0)");
  });

  it("has a fallback for unknown groups", () => {
    expect(groupColor("NOT_A_GROUP")).toHaveLength(3);
  });

  it("maps weight ratio 1 to the MBON color and clamps", () => {
    expect(weightColor(1)).toEqual(groupColor("MBON"));
    expect(weightColor(5)).toEqual(weightColor(1));
    expect(weightColor(-1)).toEqual(weightColor(0));
    expect(weightColor(0)).not.toEqual(weightColor(1));
  });

  it("dims at rest and goes to white at full activity", () => {
    const out = new Float32Array(6);
    writeActivityColor([1, 0.5, 0], 0, out, 0);
    writeActivityColor([1, 0.5, 0], 1, out, 3);
    expect(out[0]).toBeCloseTo(REST_BRIGHTNESS);
    expect(out[2]).toBe(0);
    expect(Array.from(out.slice(3))).toEqual([1, 1, 1]);
  });
});