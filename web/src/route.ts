/**
 * Hash routing for the single-page app. The list lives at `#/`, or at `#/?<filters>` when filters
 * are set, a trace at `#/trace/<id>`, the latency view at `#/latency?service=<name>` and the
 * service map at `#/map`, so the API never sees the route and a reload keeps the screen.
 */

import { EMPTY_FILTER_TEXT, parseMs, type FilterText } from "./filters";

/**
 * The screen to show: the trace list, the waterfall of one trace, a service's latency, or the
 * service map.
 */
export type Route =
  | { readonly screen: "list" }
  | { readonly screen: "trace"; readonly traceId: string }
  | { readonly screen: "latency"; readonly service: string | null }
  | { readonly screen: "map" };

const LIST_ROUTE: Route = { screen: "list" };
const MAP_ROUTE: Route = { screen: "map" };
const TRACE_HASH = /^#\/trace\/([0-9a-f]{32})$/i;
const LATENCY_HASH = /^#\/latency(?:\?(.*))?$/;
const LIST_HASH = /^#\/?(?:\?(.*))?$/;
const LIST_QUERY_MAX_LENGTH = 1024;

/**
 * Reads the screen from a location hash.
 *
 * Anything that is not `#/trace/<32 hex digits>`, `#/latency` (with an optional `service`
 * query parameter) or `#/map` shows the list. The trace id is lower-cased so that it matches the
 * ids the API returns. An empty `service` parameter means that no service is chosen.
 *
 * @param hash - The location hash, including the leading `#`, or an empty string.
 */
export function parseRoute(hash: string): Route {
  if (hash === serviceMapHash()) {
    return MAP_ROUTE;
  }
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

/**
 * The hash that opens the service map.
 *
 * @returns `#/map`.
 */
export function serviceMapHash(): string {
  return "#/map";
}

/**
 * The hash of the trace list that shows the given filters.
 *
 * Empty and invalid filter values are left out, so the hash only carries filters that the API
 * would receive. Parameters are `service`, `minMs`, `maxMs` and `error`.
 *
 * @param text - The raw filter control values.
 * @returns `#/` when no filter is set, otherwise `#/?<query>`, e.g. `#/?service=api&minMs=100`.
 */
export function listHash(text: FilterText): string {
  const params = new URLSearchParams();
  if (text.service !== "") {
    params.set("service", text.service);
  }
  const minMs = parseMs(text.minMs);
  if (minMs !== null) {
    params.set("minMs", String(minMs));
  }
  const maxMs = parseMs(text.maxMs);
  if (maxMs !== null) {
    params.set("maxMs", String(maxMs));
  }
  if (text.error !== "") {
    params.set("error", text.error);
  }
  const query = params.toString();
  return query === "" ? "#/" : `#/?${query}`;
}

/**
 * Reads the filter control values from the query of the trace list hash.
 *
 * The result is always valid: a duration that is not a decimal integer in the API range and an
 * error value other than `true` or `false` are dropped, and so is any query longer than 1024
 * characters. A hash that is not a list hash yields no filters.
 *
 * @param hash - The location hash, such as `#/?service=api&error=true`, or an empty string.
 * @returns The filter control values with the canonical text of each valid filter.
 */
export function listFilterText(hash: string): FilterText {
  const match = LIST_HASH.exec(hash);
  const query = match?.[1] ?? "";
  if (match === null || query.length > LIST_QUERY_MAX_LENGTH) {
    return EMPTY_FILTER_TEXT;
  }
  const params = new URLSearchParams(query);
  const minMs = parseMs(params.get("minMs") ?? "");
  const maxMs = parseMs(params.get("maxMs") ?? "");
  const error = params.get("error") ?? "";
  return {
    service: params.get("service") ?? "",
    minMs: minMs === null ? "" : String(minMs),
    maxMs: maxMs === null ? "" : String(maxMs),
    error: error === "true" || error === "false" ? error : "",
  };
}

/**
 * The hash to show when the list is entered from another screen through a bare `#/`, such as the
 * back link of a trace.
 *
 * When the user leaves the list for another screen, the app remembers the list hash with its
 * filters. Entering `#/` from that screen restores the remembered hash, so the filters survive the
 * trip to a trace.
 *
 * @param hash - The location hash that was entered.
 * @param remembered - The last list hash the user left, such as `#/?service=api`.
 * @returns The hash to replace `hash` with, or `null` when `hash` should stay.
 */
export function resumeListHash(hash: string, remembered: string): string | null {
  return hash === "#/" && remembered !== "#/" ? remembered : null;
}
