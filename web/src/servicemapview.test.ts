import { describe, expect, it } from "vitest";

import {
  EDGE_MAX_WIDTH,
  EDGE_MIN_WIDTH,
  edgeStrokeWidth,
  errorRate,
  formatErrorRate,
  truncateLabel,
} from "./servicemapview";

/** A small deterministic generator, so that the random cases are the same on every run. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

describe("edgeStrokeWidth", () => {
  it("gives the maximum width to the busiest edge and the minimum to a call-less edge", () => {
    expect(edgeStrokeWidth(500, 500)).toBeCloseTo(EDGE_MAX_WIDTH);
    expect(edgeStrokeWidth(0, 500)).toBe(EDGE_MIN_WIDTH);
  });

  it("gives the minimum width when there are no calls at all", () => {
    expect(edgeStrokeWidth(1, 0)).toBe(EDGE_MIN_WIDTH);
    expect(edgeStrokeWidth(0, 0)).toBe(EDGE_MIN_WIDTH);
  });

  it("treats negative, NaN and infinite counts as no calls", () => {
    for (const calls of [-3, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(edgeStrokeWidth(calls, 100), String(calls)).toBe(EDGE_MIN_WIDTH);
    }
    expect(edgeStrokeWidth(10, Number.POSITIVE_INFINITY)).toBe(EDGE_MIN_WIDTH);
  });

  it("caps the width of a count above the maximum", () => {
    expect(edgeStrokeWidth(1000, 100)).toBeCloseTo(EDGE_MAX_WIDTH);
  });

  it("grows with the logarithm of the calls", () => {
    const span = EDGE_MAX_WIDTH - EDGE_MIN_WIDTH;
    const expected = (span * (Math.log(10) - Math.log(4))) / Math.log(1001);
    expect(edgeStrokeWidth(9, 1000) - edgeStrokeWidth(3, 1000)).toBeCloseTo(expected);
  });

  it("stays within the bounds and never decreases with the calls (random cases)", () => {
    const random = lcg(7);
    for (let i = 0; i < 2000; i += 1) {
      const maxCalls = Math.floor(random() * 100_000) + 1;
      const first = Math.floor(random() * maxCalls);
      const second = Math.floor(random() * maxCalls);
      const low = Math.min(first, second);
      const high = Math.max(first, second);
      const widthLow = edgeStrokeWidth(low, maxCalls);
      const widthHigh = edgeStrokeWidth(high, maxCalls);
      expect(widthLow).toBeGreaterThanOrEqual(EDGE_MIN_WIDTH);
      expect(widthHigh).toBeLessThanOrEqual(EDGE_MAX_WIDTH);
      expect(widthHigh).toBeGreaterThanOrEqual(widthLow);
    }
  });
});

describe("errorRate", () => {
  it("is the share of calls that ended in error", () => {
    expect(errorRate(4, 1)).toBe(0.25);
    expect(errorRate(3, 0)).toBe(0);
  });

  it("is null when there were no calls", () => {
    expect(errorRate(0, 0)).toBeNull();
  });
});

describe("formatErrorRate", () => {
  it("shows the rate as a percentage with one decimal", () => {
    expect(formatErrorRate(0.125)).toBe("12.5% errors");
    expect(formatErrorRate(0)).toBe("0.0% errors");
    expect(formatErrorRate(1)).toBe("100.0% errors");
  });

  it("says that there were no calls when the rate is null", () => {
    expect(formatErrorRate(null)).toBe("no calls");
  });
});

describe("truncateLabel", () => {
  it("keeps a label that fits", () => {
    expect(truncateLabel("checkout", 8)).toBe("checkout");
    expect(truncateLabel("checkout", 20)).toBe("checkout");
    expect(truncateLabel("", 1)).toBe("");
  });

  it("cuts a long label and ends it with an ellipsis", () => {
    expect(truncateLabel("checkout-service", 8)).toBe("checkou…");
    expect(truncateLabel("abc", 2)).toBe("a…");
  });

  it("keeps a single character when the limit is 1 and the label is longer", () => {
    expect(truncateLabel("abc", 1)).toBe("…");
  });

  it("counts code points, so that a surrogate pair is never split", () => {
    expect(truncateLabel("a😀b😀c", 3)).toBe("a😀…");
    expect(truncateLabel("😀😀", 2)).toBe("😀😀");
  });

  it("rejects limits that are not integers of at least 1", () => {
    for (const maxChars of [0, -1, 1.5, Number.NaN]) {
      expect(() => truncateLabel("checkout", maxChars), String(maxChars)).toThrow(RangeError);
    }
  });
});
