import { describe, expect, it } from "vitest";

import { histogramScale } from "./histogram";

const bucket = (leNs: string, count: number) => ({ leNs, count });

describe("histogramScale", () => {
  it("gives an empty scale for no buckets", () => {
    expect(histogramScale([])).toEqual({ maxCount: 0, bars: [] });
  });

  it("keeps the bucket order and the counts", () => {
    const { bars } = histogramScale([bucket("1000", 3), bucket("2000", 0), bucket("4000", 7)]);
    expect(bars.map((bar) => bar.count)).toEqual([3, 0, 7]);
  });

  it("scales heights relative to the fullest bucket", () => {
    const scale = histogramScale([bucket("1000", 25), bucket("2000", 100), bucket("4000", 50)]);
    expect(scale.maxCount).toBe(100);
    expect(scale.bars.map((bar) => bar.heightPercent)).toEqual([25, 100, 50]);
  });

  it("draws every bar flat when all counts are zero", () => {
    const scale = histogramScale([bucket("1000", 0), bucket("2000", 0)]);
    expect(scale.maxCount).toBe(0);
    expect(scale.bars.map((bar) => bar.heightPercent)).toEqual([0, 0]);
  });

  it("keeps a single non-empty bucket at full height", () => {
    const scale = histogramScale([bucket("1000", 0), bucket("2000", 1)]);
    expect(scale.bars.map((bar) => bar.heightPercent)).toEqual([0, 100]);
  });

  it("parses the upper edges above 2^53 exactly", () => {
    const edge = "9223372036854775807";
    const [bar] = histogramScale([bucket(edge, 1)]).bars;
    expect(bar?.upperNs).toBe(9_223_372_036_854_775_807n);
  });

  it("labels each bar by its upper edge with the duration format", () => {
    const { bars } = histogramScale([
      bucket("1000", 1),
      bucket("12345678", 1),
      bucket("100000000000", 1),
    ]);
    expect(bars.map((bar) => bar.label)).toEqual(["≤ 1.0 µs", "≤ 12.3 ms", "≤ 100.0 s"]);
  });
});
