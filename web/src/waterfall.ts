/**
 * Pure layout for the trace waterfall: bar positions, service colours and time-scale ticks.
 *
 * Offsets and durations are `bigint` nanoseconds, as the API sends them. Positions are plain
 * numbers in percent of the trace width, ready for CSS. Colours are references to the
 * `--service-N` tokens defined in `styles.css`.
 */

import { durationPercent } from "./format";

/** Where a span sits in its trace: its start relative to the trace start, and its length. */
export interface Extent {
  readonly offsetNs: bigint;
  readonly durationNs: bigint;
}

/** A bar in percent of the trace width. `leftPercent + widthPercent` never exceeds 100. */
export interface BarLayout {
  readonly leftPercent: number;
  readonly widthPercent: number;
}

/** A mark on the time scale: its value in nanoseconds and its position in percent. */
export interface ScaleTick {
  readonly valueNs: bigint;
  readonly percent: number;
}

/** Narrowest bar drawn, in percent of the trace width, so that short spans stay visible. */
export const MIN_BAR_PERCENT = 0.5;

/** Number of colours in the service palette, the `--service-0` to `--service-7` tokens. */
export const SERVICE_PALETTE_SIZE = 8;

/** The time scale aims for this many intervals across the trace. */
const SCALE_INTERVALS = 5n;

const FNV_OFFSET_BASIS = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

/**
 * The end of the trace, relative to its start: the latest `offset + duration` of the spans.
 *
 * @param items - The placed spans of one trace.
 * @returns The trace duration in nanoseconds, `0n` when there are no spans.
 */
export function traceExtentNs(items: readonly Extent[]): bigint {
  return items.reduce((end, item) => {
    const itemEnd = item.offsetNs + item.durationNs;
    return itemEnd > end ? itemEnd : end;
  }, 0n);
}

/**
 * The bar of one span on a trace of `totalNs` nanoseconds.
 *
 * The width is the share of the trace the span takes, raised to {@link MIN_BAR_PERCENT} so that a
 * very short span is still visible. The left edge is then moved back, if needed, so that the bar
 * stays inside the trace. A total of zero puts every bar at the start with the minimum width.
 *
 * @param item - The span to draw.
 * @param totalNs - The trace duration in nanoseconds, from {@link traceExtentNs}.
 */
export function barLayout(item: Extent, totalNs: bigint): BarLayout {
  const widthPercent = Math.min(
    Math.max(durationPercent(item.durationNs, totalNs), MIN_BAR_PERCENT),
    100,
  );
  const leftPercent = Math.min(durationPercent(item.offsetNs, totalNs), 100 - widthPercent);
  return { leftPercent, widthPercent };
}

/**
 * Index of the palette colour of a service, from an FNV-1a hash of its UTF-8 name.
 *
 * The result depends only on the name, so a service keeps its colour across reloads and traces.
 *
 * @returns An integer in `[0, SERVICE_PALETTE_SIZE)`.
 */
export function serviceColorIndex(service: string): number {
  let hash = FNV_OFFSET_BASIS;
  for (const byte of new TextEncoder().encode(service)) {
    hash = Math.imul(hash ^ byte, FNV_PRIME);
  }
  return (hash >>> 0) % SERVICE_PALETTE_SIZE;
}

/**
 * The CSS colour of a service, as a reference to its palette token, e.g. `var(--service-3)`.
 */
export function serviceColor(service: string): string {
  return `var(--service-${serviceColorIndex(service)})`;
}

/**
 * Marks of the time scale from zero to the trace duration.
 *
 * The step is the smallest 1, 2 or 5 times a power of ten that gives about
 * {@link SCALE_INTERVALS} intervals, so the marks are round numbers such as 200 ms or 5 ms.
 *
 * @param totalNs - The trace duration in nanoseconds.
 * @returns The ticks in increasing order, starting at zero; empty when `totalNs` is not positive.
 */
export function timeScale(totalNs: bigint): ScaleTick[] {
  if (totalNs <= 0n) {
    return [];
  }
  const step = niceStep(totalNs / SCALE_INTERVALS);
  const ticks: ScaleTick[] = [];
  for (let valueNs = 0n; valueNs <= totalNs; valueNs += step) {
    ticks.push({ valueNs, percent: durationPercent(valueNs, totalNs) });
  }
  return ticks;
}

/** The smallest `1`, `2` or `5` times a power of ten that is at least `minStep` (and at least 1). */
function niceStep(minStep: bigint): bigint {
  let magnitude = 1n;
  while (magnitude * 10n <= minStep) {
    magnitude *= 10n;
  }
  for (const multiple of [1n, 2n, 5n]) {
    if (multiple * magnitude >= minStep) {
      return multiple * magnitude;
    }
  }
  return 10n * magnitude;
}
