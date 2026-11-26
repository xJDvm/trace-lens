import { describe, expect, it } from "vitest";

import { durationPercent, formatDuration, formatRelativeTime } from "./format";

const MS = 1_000_000n;
const SECOND = 1_000n * MS;

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
