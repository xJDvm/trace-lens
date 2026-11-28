import { describe, expect, it } from "vitest";

import type { FilterText } from "./filters";
import {
  latencyHash,
  listFilterText,
  listHash,
  parseRoute,
  resumeListHash,
  serviceMapHash,
  traceHash,
} from "./route";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";
const NO_FILTERS: FilterText = { service: "", minMs: "", maxMs: "", error: "" };

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
      "#/map/",
      "#/maps",
      "#/map?x=1",
      "#map",
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

describe("parseRoute for the service map", () => {
  it("reads the service map hash", () => {
    expect(parseRoute("#/map")).toEqual({ screen: "map" });
  });
});

describe("serviceMapHash", () => {
  it("is the hash that parseRoute reads as the service map", () => {
    expect(serviceMapHash()).toBe("#/map");
    expect(parseRoute(serviceMapHash())).toEqual({ screen: "map" });
  });
});

describe("listHash", () => {
  it("is the bare list hash when no filter is set", () => {
    expect(listHash(NO_FILTERS)).toBe("#/");
  });

  it("writes every set filter as a query parameter", () => {
    expect(listHash({ service: "api", minMs: "100", maxMs: "900", error: "true" })).toBe(
      "#/?service=api&minMs=100&maxMs=900&error=true",
    );
  });

  it("leaves out invalid durations and keeps only canonical numbers", () => {
    expect(listHash({ ...NO_FILTERS, minMs: "-3", maxMs: " 42 " })).toBe("#/?maxMs=42");
  });

  it("percent-encodes the service name", () => {
    expect(listHash({ ...NO_FILTERS, service: "a&b c" })).toBe("#/?service=a%26b+c");
  });
});

describe("listFilterText", () => {
  it("reads no filters from the bare list hash, an empty hash or another screen", () => {
    for (const hash of ["", "#", "#/", `#/trace/${TRACE_ID}`, "#/map", "#/latency?service=api"]) {
      expect(listFilterText(hash), hash).toEqual(NO_FILTERS);
    }
  });

  it("reads each filter from the query", () => {
    expect(listFilterText("#/?service=api&minMs=0&maxMs=900&error=false")).toEqual({
      service: "api",
      minMs: "0",
      maxMs: "900",
      error: "false",
    });
  });

  it("drops durations that are not valid API values", () => {
    expect(listFilterText("#/?minMs=-1&maxMs=1.5")).toEqual(NO_FILTERS);
    expect(listFilterText("#/?minMs=9223372036854775807")).toEqual(NO_FILTERS);
  });

  it("drops an error value other than true or false", () => {
    expect(listFilterText("#/?error=yes")).toEqual(NO_FILTERS);
    expect(listFilterText("#/?error=TRUE")).toEqual(NO_FILTERS);
  });

  it("uses the first value of a repeated parameter", () => {
    expect(listFilterText("#/?service=api&service=web").service).toBe("api");
  });

  it("ignores a query longer than 1024 characters", () => {
    expect(listFilterText(`#/?service=${"a".repeat(1024)}`)).toEqual(NO_FILTERS);
    expect(listFilterText(`#/?service=${"a".repeat(1000)}`).service).toHaveLength(1000);
  });

  it("never fails on arbitrary query text", () => {
    const alphabet = "=&?%+#/ abcMinMsErroé\u0000";
    let seed = 7;
    for (let round = 0; round < 500; round++) {
      let hash = "#/?";
      for (let index = 0; index < 40; index++) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        hash += alphabet[seed % alphabet.length];
      }
      const text = listFilterText(hash);
      expect(listFilterText(listHash(text))).toEqual(text);
    }
  });
});

describe("list filters round trip through the hash", () => {
  it("reads back the filters that listHash wrote", () => {
    const cases: FilterText[] = [
      NO_FILTERS,
      { service: "checkout", minMs: "", maxMs: "", error: "" },
      { service: "", minMs: "250", maxMs: "", error: "true" },
      { service: "", minMs: "", maxMs: "9223372036854", error: "false" },
      { service: "a&b c", minMs: "0", maxMs: "10", error: "" },
      { service: "naïve+ü?#=x", minMs: "", maxMs: "", error: "" },
    ];
    for (const text of cases) {
      expect(listFilterText(listHash(text)), listHash(text)).toEqual(text);
    }
  });

  it("keeps the list screen when the filters are in the query", () => {
    expect(parseRoute(listHash({ ...NO_FILTERS, service: "api" }))).toEqual({ screen: "list" });
  });
});

describe("resumeListHash", () => {
  it("restores the remembered list hash when the bare list hash is entered", () => {
    expect(resumeListHash("#/", "#/?service=api")).toBe("#/?service=api");
  });

  it("keeps the bare list hash when nothing was remembered", () => {
    expect(resumeListHash("#/", "#/")).toBeNull();
  });

  it("leaves every other hash alone", () => {
    expect(resumeListHash("#/?service=web", "#/?service=api")).toBeNull();
    expect(resumeListHash(`#/trace/${TRACE_ID}`, "#/?service=api")).toBeNull();
  });
});
