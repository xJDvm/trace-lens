/**
 * Hash routing for the single-page app. The list lives at `#/` and a trace at `#/trace/<id>`,
 * so the API never sees the route and a reload keeps the screen.
 */

/** The screen to show: the trace list, or the waterfall of one trace. */
export type Route =
  | { readonly screen: "list" }
  | { readonly screen: "trace"; readonly traceId: string };

const LIST_ROUTE: Route = { screen: "list" };
const TRACE_HASH = /^#\/trace\/([0-9a-f]{32})$/i;

/**
 * Reads the screen from a location hash.
 *
 * Anything that is not `#/trace/<32 hex digits>` shows the list. The trace id is lower-cased so
 * that it matches the ids the API returns.
 *
 * @param hash - The location hash, including the leading `#`, or an empty string.
 */
export function parseRoute(hash: string): Route {
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
