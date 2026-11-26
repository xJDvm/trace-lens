import { describe, expect, it } from "vitest";

import { latencyHash, parseRoute, traceHash } from "./route";

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
      "#/latency/extra",
      "#/latencies",
      "#latency",
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

describe("parseRoute for the latency view", () => {
  it("reads the service of a latency hash", () => {
    expect(parseRoute("#/latency?service=checkout")).toEqual({
      screen: "latency",
      service: "checkout",
    });
  });

  it("has no service when the parameter is missing or empty", () => {
    expect(parseRoute("#/latency")).toEqual({ screen: "latency", service: null });
    expect(parseRoute("#/latency?")).toEqual({ screen: "latency", service: null });
    expect(parseRoute("#/latency?service=")).toEqual({ screen: "latency", service: null });
  });

  it("decodes percent-encoded service names", () => {
    expect(parseRoute("#/latency?service=a%26b%20c")).toEqual({
      screen: "latency",
      service: "a&b c",
    });
  });
});

describe("latencyHash", () => {
  it("omits the query when no service is chosen", () => {
    expect(latencyHash(null)).toBe("#/latency");
    expect(latencyHash("")).toBe("#/latency");
  });

  it("encodes the service name so that parseRoute reads it back", () => {
    for (const service of ["checkout", "a&b c", "x=y?z#w", "naïve+ü"]) {
      const hash = latencyHash(service);
      expect(hash.startsWith("#/latency?service=")).toBe(true);
      expect(parseRoute(hash)).toEqual({ screen: "latency", service });
    }
  });
});
