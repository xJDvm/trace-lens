import { describe, expect, it } from "vitest";

import { EMPTY_FILTER_TEXT, MAX_DURATION_MS, parseFilters, parseMs } from "./filters";

describe("parseMs", () => {
  it("accepts decimal integers, trimming surrounding spaces", () => {
    expect(parseMs("0")).toBe(0);
    expect(parseMs("250")).toBe(250);
    expect(parseMs("  42 ")).toBe(42);
  });

  it("rejects empty, signed, fractional and non-numeric text", () => {
    for (const text of ["", "   ", "-1", "+5", "1.5", "1e3", "ten", "0x10", "1 2"]) {
      expect(parseMs(text), text).toBeNull();
    }
  });

  it("accepts the largest API value and rejects anything above it", () => {
    expect(parseMs(String(MAX_DURATION_MS))).toBe(MAX_DURATION_MS);
    expect(parseMs(String(MAX_DURATION_MS + 1))).toBeNull();
  });

  it("rejects values beyond the safe integer range", () => {
    expect(parseMs("9007199254740993")).toBeNull();
  });
});

describe("parseFilters", () => {
  it("applies no filter to the empty form", () => {
    expect(parseFilters(EMPTY_FILTER_TEXT)).toEqual({
      service: null,
      minMs: null,
      maxMs: null,
      error: null,
    });
  });

  it("maps every control to its request filter", () => {
    expect(
      parseFilters({ service: "api", minMs: "0", maxMs: "900", error: "false" }),
    ).toEqual({ service: "api", minMs: 0, maxMs: 900, error: false });
    expect(parseFilters({ service: "", minMs: "", maxMs: "", error: "true" }).error).toBe(true);
  });

  it("drops an invalid duration instead of sending it", () => {
    expect(parseFilters({ ...EMPTY_FILTER_TEXT, minMs: "-3", maxMs: "x" })).toMatchObject({
      minMs: null,
      maxMs: null,
    });
  });
});
