import type { TraceFilters } from "./api";

/** Largest duration the API accepts: `2^63 - 1` nanoseconds, in whole milliseconds. */
export const MAX_DURATION_MS = 9_223_372_036_854;

/** Raw values of the filter controls, as the user typed or selected them. */
export interface FilterText {
  readonly service: string;
  readonly minMs: string;
  readonly maxMs: string;
  readonly error: "" | "true" | "false";
}

export const EMPTY_FILTER_TEXT: FilterText = { service: "", minMs: "", maxMs: "", error: "" };

/**
 * Turns the raw control values into request filters.
 *
 * Empty or invalid duration text means "not applied", so it is never sent to the API.
 */
export function parseFilters(text: FilterText): TraceFilters {
  return {
    service: text.service === "" ? null : text.service,
    minMs: parseMs(text.minMs),
    maxMs: parseMs(text.maxMs),
    error: text.error === "" ? null : text.error === "true",
  };
}

/**
 * Parses a duration in whole milliseconds.
 *
 * @returns The value, or `null` when the text is not a decimal integer in the API range.
 */
export function parseMs(text: string): number | null {
  const trimmed = text.trim();
  if (!/^[0-9]+$/.test(trimmed)) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value <= MAX_DURATION_MS ? value : null;
}
