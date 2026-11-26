/**
 * Pure formatting helpers for the trace list and the trace view. Times arrive from the API as
 * decimal strings of nanoseconds, so they are handled as `bigint` to stay exact above 2^53.
 */

import type { AttributeValue } from "./api";

interface DurationUnit {
  readonly suffix: string;
  /** Nanoseconds in one unit. */
  readonly scale: bigint;
}

const NANOSECONDS_PER_MILLISECOND = 1_000_000n;

const DURATION_UNITS: readonly DurationUnit[] = [
  { suffix: "ns", scale: 1n },
  { suffix: "µs", scale: 1_000n },
  { suffix: "ms", scale: NANOSECONDS_PER_MILLISECOND },
  { suffix: "s", scale: 1_000_000_000n },
];

/** Tenths of a unit, the precision shown for every unit except nanoseconds. */
const TENTHS_PER_THOUSAND_UNITS = 10_000n;

const RELATIVE_UNITS: readonly (readonly [Intl.RelativeTimeFormatUnit, number])[] = [
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
  ["second", 1_000],
];

const relativeTimeFormat = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/**
 * Formats a non-negative duration in nanoseconds, e.g. `12.3 ms`.
 *
 * The largest unit that keeps the value below 1000 is chosen, rounded half up to one decimal.
 * Nanoseconds are shown as whole numbers.
 *
 * @param ns - Duration in nanoseconds, zero or more.
 * @returns The value with its unit suffix.
 */
export function formatDuration(ns: bigint): string {
  let index = 0;
  while (index + 1 < DURATION_UNITS.length && ns >= unitAt(index + 1).scale) {
    index += 1;
  }
  if (index === 0) {
    return `${ns} ns`;
  }
  let tenths = tenthsOf(ns, unitAt(index).scale);
  // Rounding can reach 1000 of a unit (999 950 ns is "1000.0 µs"); show the next unit instead.
  if (tenths >= TENTHS_PER_THOUSAND_UNITS && index + 1 < DURATION_UNITS.length) {
    index += 1;
    tenths = tenthsOf(ns, unitAt(index).scale);
  }
  return `${tenths / 10n}.${tenths % 10n} ${unitAt(index).suffix}`;
}

/**
 * Describes when a trace started, relative to the current time, e.g. `5 minutes ago`.
 *
 * @param startNs - Start time in nanoseconds since the Unix epoch.
 * @param nowMs - Current time in milliseconds since the Unix epoch.
 * @returns An English relative-time phrase; times in the future read as `in ...`.
 */
export function formatRelativeTime(startNs: bigint, nowMs: number): string {
  const ageMs = nowMs - Number(startNs / NANOSECONDS_PER_MILLISECOND);
  const [unit, unitMs] = RELATIVE_UNITS.find(([, size]) => Math.abs(ageMs) >= size) ?? [
    "second",
    1_000,
  ];
  return relativeTimeFormat.format(-Math.round(ageMs / unitMs), unit);
}

/**
 * The share of `maxNs` that `ns` represents, as a percentage for a bar width.
 *
 * @param ns - The value to draw, zero or more.
 * @param maxNs - The scale maximum; zero yields 0.
 * @returns A number in `[0, 100]` when `ns <= maxNs`, with two decimals of precision.
 */
export function durationPercent(ns: bigint, maxNs: bigint): number {
  if (maxNs <= 0n) {
    return 0;
  }
  return Number((ns * 10_000n) / maxNs) / 100;
}

/**
 * The text of an attribute value. Booleans and numbers are written as they would be in code.
 *
 * @param value - An attribute value in the OTLP JSON mapping.
 */
export function attributeText(value: AttributeValue): string {
  if ("stringValue" in value) {
    return value.stringValue;
  }
  if ("intValue" in value) {
    return value.intValue;
  }
  if ("doubleValue" in value) {
    return String(value.doubleValue);
  }
  return String(value.boolValue);
}

const STATUS_LABELS: Readonly<Record<number, string>> = { 0: "Unset", 1: "OK", 2: "Error" };

/**
 * The name of a span status code: `0` is unset, `1` is OK and `2` is error.
 *
 * @returns The label, or `Code <n>` for a code the OpenTelemetry specification does not define.
 */
export function statusLabel(code: number): string {
  return STATUS_LABELS[code] ?? `Code ${code}`;
}

function unitAt(index: number): DurationUnit {
  const unit = DURATION_UNITS[index];
  if (unit === undefined) {
    throw new RangeError(`no duration unit at index ${index}`);
  }
  return unit;
}

/** `ns / scale` in tenths, rounded half up. */
function tenthsOf(ns: bigint, scale: bigint): bigint {
  return (ns * 10n + scale / 2n) / scale;
}
