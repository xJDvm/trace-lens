/**
 * Pure presentation helpers of the service map: edge thickness, error rates and label length.
 *
 * Edge thickness grows with the logarithm of the call count, so that one busy edge does not hide
 * the rest. The values are in SVG user units of the drawing (see `components/ServiceMap.tsx`).
 */

/** Stroke width of the least called edge, in SVG user units. */
export const EDGE_MIN_WIDTH = 1.5;
/** Stroke width of the most called edge, in SVG user units. */
export const EDGE_MAX_WIDTH = 8;

/**
 * Stroke width of an edge: linear in `log(1 + calls)` between {@link EDGE_MIN_WIDTH} and
 * {@link EDGE_MAX_WIDTH}, where `maxCalls` is the call count of the busiest edge.
 *
 * Counts that are zero, negative or not finite get the minimum width. A count above `maxCalls`
 * gets the maximum width.
 *
 * @param calls - The calls of the edge.
 * @param maxCalls - The largest call count among all the edges of the map.
 */
export function edgeStrokeWidth(calls: number, maxCalls: number): number {
  if (!(calls > 0) || !(maxCalls > 0) || !Number.isFinite(calls) || !Number.isFinite(maxCalls)) {
    return EDGE_MIN_WIDTH;
  }
  const ratio = Math.log1p(Math.min(calls, maxCalls)) / Math.log1p(maxCalls);
  return EDGE_MIN_WIDTH + (EDGE_MAX_WIDTH - EDGE_MIN_WIDTH) * ratio;
}

/**
 * The share of calls that ended in error.
 *
 * @param calls - The calls received by a service.
 * @param errors - The calls among them that ended in error.
 * @returns `errors / calls`, or `null` when there were no calls.
 */
export function errorRate(calls: number, errors: number): number | null {
  return calls > 0 ? errors / calls : null;
}

/**
 * The error rate as text for a node, e.g. `12.5% errors`, or `no calls` when the rate is `null`.
 *
 * @param rate - A rate as returned by {@link errorRate}.
 */
export function formatErrorRate(rate: number | null): string {
  return rate === null ? "no calls" : `${(rate * 100).toFixed(1)}% errors`;
}

/**
 * Shortens a label to at most `maxChars` characters, ending with an ellipsis when it is cut.
 *
 * Characters are counted as code points, so a surrogate pair is never split.
 *
 * @param text - The label to shorten.
 * @param maxChars - The longest allowed label, in code points; at least 1.
 * @throws {RangeError} When `maxChars` is not an integer of at least 1.
 */
export function truncateLabel(text: string, maxChars: number): string {
  if (!Number.isInteger(maxChars) || maxChars < 1) {
    throw new RangeError(`maxChars must be an integer of at least 1, got ${maxChars}`);
  }
  const chars = Array.from(text);
  if (chars.length <= maxChars) {
    return text;
  }
  return `${chars.slice(0, maxChars - 1).join("")}…`;
}
