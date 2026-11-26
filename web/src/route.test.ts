import { describe, expect, it } from "vitest";

import { parseRoute, traceHash } from "./route";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";

describe("parseRoute", () => {
  it("shows the list for an empty hash or the root path", () => {
    expect(parseRoute("")).toEqual({ screen: "list" });
    expect(parseRoute("#")).toEqual({ screen: "list" });
    expect(parseRoute("#/")).toEqual({ screen: "list" });
  });

  it("reads the trace id of a trace hash", () => {
    expect(parseRoute(`#/trace/${TRACE_ID}`)).toEqual({ screen: "trace", traceId: TRACE_ID });
  });

  it("lower-cases the trace id", () => {
    expect(parseRoute(`#/trace/${TRACE_ID.toUpperCase()}`)).toEqual({
      screen: "trace",
      traceId: TRACE_ID,
    });
  });

  it("falls back to the list for anything that is not a valid trace hash", () => {
    const invalid = [
      "#/trace/",
      "#/trace",
      `#/trace/${TRACE_ID.slice(1)}`,
      `#/trace/${TRACE_ID}0`,
      `#/trace/${TRACE_ID}/extra`,
      `#/trace/${"g".repeat(32)}`,
      `#/trace/${TRACE_ID}?x=1`,
      `trace/${TRACE_ID}`,
      `#/traces/${TRACE_ID}`,
    ];
    for (const hash of invalid) {
      expect(parseRoute(hash), hash).toEqual({ screen: "list" });
    }
  });
});

describe("traceHash", () => {
  it("builds the hash that parseRoute reads back", () => {
    expect(traceHash(TRACE_ID)).toBe(`#/trace/${TRACE_ID}`);
    expect(parseRoute(traceHash(TRACE_ID))).toEqual({ screen: "trace", traceId: TRACE_ID });
  });
});
