/**
 * Typed client for the trace-lens query API (see `docs/DESIGN.md`, section API).
 *
 * Requests are relative, so the Vite dev server proxies them to the backend. Identifiers and
 * nanosecond values arrive as strings because they can exceed the integer range of JavaScript.
 */

/** One trace in a list page, as returned by `GET /api/traces`. */
export interface TraceSummary {
  readonly traceId: string;
  readonly startNs: string;
  readonly endNs: string;
  readonly durationNs: string;
  readonly spanCount: number;
  readonly errorCount: number;
  readonly rootService: string;
  readonly rootName: string;
}

/** One page of traces, newest first. The `next*` fields are `null` past the last page. */
export interface TracePage {
  readonly traces: readonly TraceSummary[];
  readonly nextBefore: string | null;
  readonly nextBeforeTraceId: string | null;
}

/** Position of the last trace of the previous page, sent back to fetch the next one. */
export interface TraceCursor {
  readonly before: string;
  readonly beforeTraceId: string;
}

/** Server-side filters of the trace list. `null` means the filter is not applied. */
export interface TraceFilters {
  readonly service: string | null;
  readonly minMs: number | null;
  readonly maxMs: number | null;
  readonly error: boolean | null;
}

/**
 * An attribute value in the OTLP JSON mapping. Integers travel as strings, since they can exceed
 * the safe integer range of JavaScript.
 */
export type AttributeValue =
  | { readonly stringValue: string }
  | { readonly intValue: string }
  | { readonly doubleValue: number }
  | { readonly boolValue: boolean };

/** One attribute of a span, as returned by `GET /api/traces/{trace_id}`. */
export interface SpanAttribute {
  readonly key: string;
  readonly value: AttributeValue;
}

/** One span of a trace, placed in the waterfall by its `depth` and `offsetNs`. */
export interface SpanRow {
  readonly traceId: string;
  readonly spanId: string;
  readonly parentSpanId: string | null;
  readonly service: string;
  readonly name: string;
  readonly kind: number;
  readonly startNs: string;
  readonly endNs: string;
  readonly durationNs: string;
  readonly statusCode: number;
  readonly statusMessage: string;
  readonly attributes: readonly SpanAttribute[];
  readonly depth: number;
  readonly offsetNs: string;
}

/** A trace with its spans in waterfall order, as returned by `GET /api/traces/{trace_id}`. */
export interface TraceDetail {
  readonly summary: TraceSummary;
  readonly rows: readonly SpanRow[];
  readonly orphans: number;
}

/** One bucket of a latency histogram. Its bounds are `(previous leNs, leNs]`. */
export interface LatencyBucket {
  /** Upper bound of the bucket in nanoseconds, as a decimal string. */
  readonly leNs: string;
  readonly count: number;
}

/**
 * Latency statistics of the most recent spans of a service, as returned by
 * `GET /api/stats/latency`. The percentiles are `null` when there are no spans.
 */
export interface LatencyStats {
  readonly count: number;
  readonly p50: string | null;
  readonly p95: string | null;
  readonly p99: string | null;
  readonly histogram: readonly LatencyBucket[];
}

/** An HTTP error answered by the API, carrying the status and the server's message. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Builds the URL of one page of `GET /api/traces`.
 *
 * @param filters - Filters to apply; `null` fields are omitted from the query string.
 * @param cursor - Position to continue from, or `null` for the first page.
 * @returns A path with its query string, e.g. `/api/traces?service=api&minMs=100`.
 */
export function buildTracesUrl(filters: TraceFilters, cursor: TraceCursor | null): string {
  const params = new URLSearchParams();
  if (filters.service !== null) {
    params.set("service", filters.service);
  }
  if (filters.minMs !== null) {
    params.set("minMs", String(filters.minMs));
  }
  if (filters.maxMs !== null) {
    params.set("maxMs", String(filters.maxMs));
  }
  if (filters.error !== null) {
    params.set("error", String(filters.error));
  }
  if (cursor !== null) {
    params.set("before", cursor.before);
    params.set("beforeTraceId", cursor.beforeTraceId);
  }
  const query = params.toString();
  return query === "" ? "/api/traces" : `/api/traces?${query}`;
}

/**
 * The cursor for the page after `page`, or `null` when `page` is the last one.
 *
 * @param page - A page returned by `GET /api/traces`.
 */
export function nextCursor(page: TracePage): TraceCursor | null {
  if (page.nextBefore === null || page.nextBeforeTraceId === null) {
    return null;
  }
  return { before: page.nextBefore, beforeTraceId: page.nextBeforeTraceId };
}

/**
 * Fetches one page of traces.
 *
 * @throws {ApiError} When the API answers with a non-2xx status.
 */
export async function fetchTraces(
  filters: TraceFilters,
  cursor: TraceCursor | null,
  signal?: AbortSignal,
): Promise<TracePage> {
  const response = await fetch(buildTracesUrl(filters, cursor), {
    headers: { Accept: "application/json" },
    signal,
  });
  return readJson<TracePage>(response);
}

/**
 * Fetches the names of the services that have reported spans.
 *
 * @throws {ApiError} When the API answers with a non-2xx status.
 */
export async function fetchServices(signal?: AbortSignal): Promise<string[]> {
  const response = await fetch("/api/services", {
    headers: { Accept: "application/json" },
    signal,
  });
  return readJson<string[]>(response);
}

/**
 * Builds the URL of `GET /api/stats/latency` for one service.
 *
 * @param service - The service name; it is percent-encoded in the query string.
 * @returns A path such as `/api/stats/latency?service=checkout`.
 */
export function buildLatencyUrl(service: string): string {
  return `/api/stats/latency?${new URLSearchParams({ service }).toString()}`;
}

/**
 * Fetches the latency statistics of one service.
 *
 * @throws {ApiError} When the API answers with a non-2xx status, e.g. 422 for an invalid name.
 */
export async function fetchLatency(service: string, signal?: AbortSignal): Promise<LatencyStats> {
  const response = await fetch(buildLatencyUrl(service), {
    headers: { Accept: "application/json" },
    signal,
  });
  return readJson<LatencyStats>(response);
}

/**
 * Fetches one trace with its span tree.
 *
 * @param traceId - The 32-character hex trace id.
 * @throws {ApiError} When the API answers with a non-2xx status, e.g. 404 for an unknown trace.
 */
export async function fetchTrace(traceId: string, signal?: AbortSignal): Promise<TraceDetail> {
  const response = await fetch(`/api/traces/${encodeURIComponent(traceId)}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  return readJson<TraceDetail>(response);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

/** The `detail` of a FastAPI error body, or a generic message when there is none. */
async function errorMessage(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => undefined);
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") {
      return detail[0].msg;
    }
  }
  return `request failed with HTTP ${response.status}`;
}
