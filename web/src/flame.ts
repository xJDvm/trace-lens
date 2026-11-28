/**
 * Pure layout for the flame graph of one trace: a frame per span, placed by its depth in the span
 * tree and by its time range. No React here.
 *
 * Each child is clipped to the time range of its parent, so a frame always lies inside the frame
 * of its parent. Spans whose parent is missing from the trace, or that take part in a parent cycle,
 * become roots.
 */

import type { SpanRow } from "./api";
import { traceExtentNs } from "./waterfall";

/** One box of the flame graph. The horizontal extent is a fraction of the trace's time range. */
export interface Frame {
  readonly spanId: string;
  /** Number of ancestors kept in the tree; roots have depth `0`. */
  readonly depth: number;
  /** Start of the frame, in `[0, 1]`. */
  readonly x0: number;
  /** End of the frame, in `[x0, 1]`. */
  readonly x1: number;
  /** The span name. */
  readonly label: string;
  readonly service: string;
  /** Whether the span ended in error. */
  readonly isError: boolean;
}

/** `StatusCode` of an OpenTelemetry span that ended in error. */
const STATUS_ERROR = 2;

/** Denominator of the fractions: times are divided by the trace duration in this many parts. */
const FRACTION_SCALE = 1_000_000_000n;

/** A span with its time range in nanoseconds relative to the trace start. */
interface Node {
  readonly row: SpanRow;
  readonly startNs: bigint;
  readonly endNs: bigint;
}

/** A node waiting to be placed, with the time range its parent allows it to occupy. */
interface Pending {
  readonly node: Node;
  readonly depth: number;
  readonly lowNs: bigint;
  readonly highNs: bigint;
}

/**
 * The frames of a flame graph, in depth-first order: every frame comes before its children.
 *
 * Span ids must be unique within the trace, as the API guarantees. A span is clipped to the range
 * of its parent, so children never extend past it. Siblings keep the order of their start times,
 * and ties are broken by span id.
 *
 * @param spans - The spans of one trace, in any order.
 * @returns One frame per span; empty when there are no spans.
 */
export function flameFrames(spans: readonly SpanRow[]): Frame[] {
  const nodes = spans.map(toNode).sort(compareNodes);
  if (nodes.length === 0) {
    return [];
  }
  const totalNs = traceExtentNs(
    nodes.map((node) => ({
      offsetNs: node.startNs,
      durationNs: node.endNs - node.startNs,
    })),
  );
  const fraction = (ns: bigint): number =>
    totalNs > 0n
      ? Number((ns * FRACTION_SCALE) / totalNs) / Number(FRACTION_SCALE)
      : 0;

  const ids = new Set(nodes.map((node) => node.row.spanId));
  const children = new Map<string, Node[]>();
  const roots: Node[] = [];
  for (const node of nodes) {
    const parentId = node.row.parentSpanId;
    if (parentId !== null && ids.has(parentId)) {
      const siblings = children.get(parentId) ?? [];
      siblings.push(node);
      children.set(parentId, siblings);
    } else {
      roots.push(node);
    }
  }

  const frames: Frame[] = [];
  const placed = new Set<string>();
  // Roots first; then any span not reached from them, which can only sit on a parent cycle.
  for (const start of [...roots, ...nodes]) {
    const pending: Pending[] = [
      { node: start, depth: 0, lowNs: 0n, highNs: totalNs },
    ];
    for (let item = pending.pop(); item !== undefined; item = pending.pop()) {
      const { node, depth, lowNs, highNs } = item;
      const spanId = node.row.spanId;
      if (placed.has(spanId)) {
        continue;
      }
      placed.add(spanId);
      const startNs = clamp(node.startNs, lowNs, highNs);
      const endNs = clamp(node.endNs, startNs, highNs);
      frames.push({
        spanId,
        depth,
        x0: fraction(startNs),
        x1: fraction(endNs),
        label: node.row.name,
        service: node.row.service,
        isError: node.row.statusCode === STATUS_ERROR,
      });
      const kids = children.get(spanId) ?? [];
      for (const kid of [...kids].reverse()) {
        pending.push({
          node: kid,
          depth: depth + 1,
          lowNs: startNs,
          highNs: endNs,
        });
      }
    }
  }
  return frames;
}

/** The span with its time range, from the decimal strings the API sends. */
function toNode(row: SpanRow): Node {
  const startNs = BigInt(row.offsetNs);
  const durationNs = BigInt(row.durationNs);
  return { row, startNs, endNs: startNs + (durationNs > 0n ? durationNs : 0n) };
}

/** Orders spans by start time, then by span id, so that the output does not depend on input order. */
function compareNodes(a: Node, b: Node): number {
  if (a.startNs !== b.startNs) {
    return a.startNs < b.startNs ? -1 : 1;
  }
  return a.row.spanId < b.row.spanId ? -1 : a.row.spanId > b.row.spanId ? 1 : 0;
}

/** `value` limited to `[low, high]`. */
function clamp(value: bigint, low: bigint, high: bigint): bigint {
  if (value < low) {
    return low;
  }
  return value > high ? high : value;
}
