/**
 * Hash routing for the single-page app. The list lives at `#/`, a trace at `#/trace/<id>` and the
 * latency view at `#/latency?service=<name>`, so the API never sees the route and a reload keeps
 * the screen.
 */

/** The screen to show: the trace list, the waterfall of one trace, or a service's latency. */
export type Route =
  | { readonly screen: "list" }
  | { readonly screen: "trace"; readonly traceId: string }
  | { readonly screen: "latency"; readonly service: string | null };

const LIST_ROUTE: Route = { screen: "list" };
const TRACE_HASH = /^#\/trace\/([0-9a-f]{32})$/i;
const LATENCY_HASH = /^#\/latency(?:\?(.*))?$/;

/**
 * Reads the screen from a location hash.
 *
 * Anything that is not `#/trace/<32 hex digits>` or `#/latency` (with an optional `service`
 * query parameter) shows the list. The trace id is lower-cased so that it matches the ids the API
 * returns. An empty `service` parameter means that no service is chosen.
 *
 * @param hash - The location hash, including the leading `#`, or an empty string.
 */
export function parseRoute(hash: string): Route {
  const latency = LATENCY_HASH.exec(hash);
  if (latency !== null) {
    const service = new URLSearchParams(latency[1] ?? "").get("service");
    return { screen: "latency", service: service === null || service === "" ? null : service };
  }
  const traceId = TRACE_HASH.exec(hash)?.[1];
  if (traceId === undefined) {
    return LIST_ROUTE;
  }
  return { screen: "trace", traceId: traceId.toLowerCase() };
}

/**
 * The hash that opens the waterfall of a trace.
 *
 * @param traceId - A trace id as returned by the API.
 * @returns A hash such as `#/trace/0af7651916cd43dd8448eb211c80319c`.
 */
export function traceHash(traceId: string): string {
  return `#/trace/${traceId}`;
}

/**
 * The hash that opens the latency view of a service.
 *
 * @param service - The service name, or `null` to open the view without a service chosen.
 * @returns `#/latency` or `#/latency?service=<name>`, with the name percent-encoded.
 */
export function latencyHash(service: string | null): string {
  if (service === null || service === "") {
    return "#/latency";
  }
  return `#/latency?service=${encodeURIComponent(service)}`;
}
