import { describe, expect, it } from "vitest";

import {
  attributeText,
  durationPercent,
  formatDuration,
  formatOptionalDuration,
  formatRelativeTime,
  statusLabel,
} from "./format";

const MS = 1_000_000n;
const SECOND = 1_000n * MS;

describe("formatOptionalDuration", () => {
  it("formats a decimal string of nanoseconds", () => {
    expect(formatOptionalDuration("12345678")).toBe("12.3 ms");
    expect(formatOptionalDuration("0")).toBe("0 ns");
  });

  it("shows an em dash when there is no value", () => {
    expect(formatOptionalDuration(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("shows whole nanoseconds below one microsecond", () => {
    expect(formatDuration(0n)).toBe("0 ns");
    expect(formatDuration(999n)).toBe("999 ns");
  });

  it("switches to microseconds at 1000 ns", () => {
    expect(formatDuration(1_000n)).toBe("1.0 µs");
    expect(formatDuration(1_550n)).toBe("1.6 µs");
  });

  it("shows milliseconds with one decimal, as in the design examples", () => {
    expect(formatDuration(12_345_678n)).toBe("12.3 ms");
    expect(formatDuration(1_500n * 1_000n)).toBe("1.5 ms");
  });

  it("rounds half up at the tenth", () => {
    expect(formatDuration(12_350_000n)).toBe("12.4 ms");
    expect(formatDuration(12_349_999n)).toBe("12.3 ms");
  });

  it("moves to the next unit instead of printing 1000 of a unit", () => {
    expect(formatDuration(999_949n)).toBe("999.9 µs");
    expect(formatDuration(999_950n)).toBe("1.0 ms");
    expect(formatDuration(999_999_950n)).toBe("1.0 s");
  });

  it("shows seconds for durations of one second and more", () => {
    expect(formatDuration(SECOND)).toBe("1.0 s");
    expect(formatDuration(90n * SECOND)).toBe("90.0 s");
    expect(formatDuration(3_600n * SECOND)).toBe("3600.0 s");
  });

  it("stays exact for values beyond the safe integer range", () => {
    const max = 2n ** 63n - 1n;
    expect(formatDuration(max)).toBe("9223372036.9 s");
  });
});

describe("formatRelativeTime", () => {
  const NOW_MS = 1_800_000_000_000;
  const at = (agoMs: number): bigint => BigInt(NOW_MS - agoMs) * MS;

  it("reads a trace that started just now as now", () => {
    expect(formatRelativeTime(at(0), NOW_MS)).toBe("now");
  });

  it("uses seconds below a minute", () => {
    expect(formatRelativeTime(at(30_000), NOW_MS)).toBe("30 seconds ago");
  });

  it("uses minutes, hours and days at their thresholds", () => {
    expect(formatRelativeTime(at(60_000), NOW_MS)).toBe("1 minute ago");
    expect(formatRelativeTime(at(5 * 60_000), NOW_MS)).toBe("5 minutes ago");
    expect(formatRelativeTime(at(3_600_000), NOW_MS)).toBe("1 hour ago");
    expect(formatRelativeTime(at(86_400_000), NOW_MS)).toBe("yesterday");
    expect(formatRelativeTime(at(4 * 86_400_000), NOW_MS)).toBe("4 days ago");
  });

  it("reads a start time after now as a future time", () => {
    expect(formatRelativeTime(at(-120_000), NOW_MS)).toBe("in 2 minutes");
  });
});

describe("durationPercent", () => {
  it("scales a value against the maximum", () => {
    expect(durationPercent(0n, 100n)).toBe(0);
    expect(durationPercent(50n, 100n)).toBe(50);
    expect(durationPercent(100n, 100n)).toBe(100);
  });

  it("keeps two decimals", () => {
    expect(durationPercent(1n, 3n)).toBe(33.33);
  });

  it("returns 0 when the maximum is zero", () => {
    expect(durationPercent(5n, 0n)).toBe(0);
  });
});

describe("attributeText", () => {
  it("returns string values as they are, including the empty string", () => {
    expect(attributeText({ stringValue: "GET" })).toBe("GET");
    expect(attributeText({ stringValue: "" })).toBe("");
  });

  it("keeps the digits of integers beyond the safe range", () => {
    expect(attributeText({ intValue: "9223372036854775807" })).toBe("9223372036854775807");
  });

  it("writes doubles and booleans as they are written in code", () => {
    expect(attributeText({ doubleValue: 0.5 })).toBe("0.5");
    expect(attributeText({ doubleValue: 3 })).toBe("3");
    expect(attributeText({ boolValue: true })).toBe("true");
    expect(attributeText({ boolValue: false })).toBe("false");
  });
});

describe("statusLabel", () => {
  it("names the three OpenTelemetry status codes", () => {
    expect(statusLabel(0)).toBe("Unset");
    expect(statusLabel(1)).toBe("OK");
    expect(statusLabel(2)).toBe("Error");
  });

  it("shows undefined codes by number", () => {
    expect(statusLabel(7)).toBe("Code 7");
  });
});
