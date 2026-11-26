import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  buildTracesUrl,
  fetchServices,
  fetchTrace,
  fetchTraces,
  nextCursor,
  type TraceFilters,
  type TracePage,
} from "./api";

const NO_FILTERS: TraceFilters = { service: null, minMs: null, maxMs: null, error: null };
const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";
const CURSOR = { before: "1700000000000000000", beforeTraceId: "a".repeat(32) };

describe("buildTracesUrl", () => {
  it("has no query string when nothing is set", () => {
    expect(buildTracesUrl(NO_FILTERS, null)).toBe("/api/traces");
  });

  it("sends every set filter, including zero durations and false", () => {
    const url = buildTracesUrl({ service: "checkout", minMs: 0, maxMs: 250, error: false }, null);
    const params = new URL(url, "http://localhost").searchParams;
    expect(params.get("service")).toBe("checkout");
    expect(params.get("minMs")).toBe("0");
    expect(params.get("maxMs")).toBe("250");
    expect(params.get("error")).toBe("false");
  });

  it("encodes the service name", () => {
    const url = buildTracesUrl({ ...NO_FILTERS, service: "a&b c" }, null);
    expect(new URL(url, "http://localhost").searchParams.get("service")).toBe("a&b c");
  });

  it("adds the cursor as before and beforeTraceId", () => {
    const params = new URL(buildTracesUrl(NO_FILTERS, CURSOR), "http://localhost").searchParams;
    expect(params.get("before")).toBe(CURSOR.before);
    expect(params.get("beforeTraceId")).toBe(CURSOR.beforeTraceId);
  });
});

describe("nextCursor", () => {
  const page = (nextBefore: string | null, nextBeforeTraceId: string | null): TracePage => ({
    traces: [],
    nextBefore,
    nextBeforeTraceId,
  });

  it("returns the cursor when the page carries one", () => {
    expect(nextCursor(page(CURSOR.before, CURSOR.beforeTraceId))).toEqual(CURSOR);
  });

  it("returns null when either field is missing", () => {
    expect(nextCursor(page(null, null))).toBeNull();
    expect(nextCursor(page(CURSOR.before, null))).toBeNull();
    expect(nextCursor(page(null, CURSOR.beforeTraceId))).toBeNull();
  });
});

describe("fetch helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed page on success", async () => {
    const body: TracePage = { traces: [], nextBefore: null, nextBeforeTraceId: null };
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(body)));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchTraces(NO_FILTERS, null)).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith("/api/traces", expect.anything());
  });

  it("raises an ApiError carrying the server's string detail", async () => {
    vi.stubGlobal(
      "fetch",
      () =>
        Promise.resolve(
          Response.json({ detail: "beforeTraceId requires before" }, { status: 422 }),
        ),
    );
    const error = await fetchTraces(NO_FILTERS, null).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: "beforeTraceId requires before" });
  });

  it("uses the first message of a validation error list", async () => {
    vi.stubGlobal(
      "fetch",
      () =>
        Promise.resolve(
          Response.json({ detail: [{ msg: "Input should be less than or equal to 500" }] }, {
            status: 422,
          }),
        ),
    );
    await expect(fetchTraces(NO_FILTERS, null)).rejects.toMatchObject({
      message: "Input should be less than or equal to 500",
    });
  });

  it("requests one trace by its id and returns the detail", async () => {
    const detail = {
      summary: { traceId: TRACE_ID },
      rows: [],
      orphans: 0,
    };
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(detail)));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchTrace(TRACE_ID)).resolves.toEqual(detail);
    expect(fetchMock).toHaveBeenCalledWith(`/api/traces/${TRACE_ID}`, expect.anything());
  });

  it("raises an ApiError with the detail of a 404", async () => {
    vi.stubGlobal(
      "fetch",
      () => Promise.resolve(Response.json({ detail: "trace not found" }, { status: 404 })),
    );
    await expect(fetchTrace(TRACE_ID)).rejects.toMatchObject({
      status: 404,
      message: "trace not found",
    });
  });

  it("falls back to the status when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("oops", { status: 500 })));
    await expect(fetchServices()).rejects.toMatchObject({
      status: 500,
      message: "request failed with HTTP 500",
    });
  });
});
