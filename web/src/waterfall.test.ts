import { describe, expect, it } from "vitest";

import {
  barLayout,
  MIN_BAR_PERCENT,
  SERVICE_PALETTE_SIZE,
  serviceColor,
  serviceColorIndex,
  timeScale,
  traceExtentNs,
} from "./waterfall";

const MS = 1_000_000n;
const SECOND = 1_000n * MS;

/** A deterministic pseudo-random sequence (xorshift32), so property checks are reproducible. */
function randomSource(seed: number): () => number {
  let state = seed;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x1_0000_0000;
  };
}

/** A random non-negative bigint below `bound`, built from 32-bit draws. */
function randomBelow(next: () => number, bound: bigint): bigint {
  const draw = BigInt(Math.floor(next() * 0x1_0000_0000)) << 32n;
  return (draw | BigInt(Math.floor(next() * 0x1_0000_0000))) % bound;
}

describe("barLayout", () => {
  it("places a span by its share of the trace", () => {
    expect(barLayout({ offsetNs: 0n, durationNs: 250n }, 1_000n)).toEqual({
      leftPercent: 0,
      widthPercent: 25,
    });
    expect(barLayout({ offsetNs: 500n, durationNs: 100n }, 1_000n)).toEqual({
      leftPercent: 50,
      widthPercent: 10,
    });
  });

  it("draws a span covering the whole trace at full width", () => {
    expect(barLayout({ offsetNs: 0n, durationNs: 1_000n }, 1_000n)).toEqual({
      leftPercent: 0,
      widthPercent: 100,
    });
  });

  it("raises a very short span to the minimum visible width", () => {
    const layout = barLayout({ offsetNs: 10n, durationNs: 1n }, SECOND);
    expect(layout.widthPercent).toBe(MIN_BAR_PERCENT);
  });

  it("gives a zero-length span the minimum visible width", () => {
    expect(barLayout({ offsetNs: 400n, durationNs: 0n }, 1_000n)).toEqual({
      leftPercent: 40,
      widthPercent: MIN_BAR_PERCENT,
    });
  });

  it("keeps the minimum width when the span starts at the very end", () => {
    expect(barLayout({ offsetNs: 1_000n, durationNs: 0n }, 1_000n)).toEqual({
      leftPercent: 100 - MIN_BAR_PERCENT,
      widthPercent: MIN_BAR_PERCENT,
    });
  });

  it("puts every bar at the start when the trace has no duration", () => {
    expect(barLayout({ offsetNs: 0n, durationNs: 0n }, 0n)).toEqual({
      leftPercent: 0,
      widthPercent: MIN_BAR_PERCENT,
    });
  });

  it("keeps every bar inside the trace for random spans", () => {
    const next = randomSource(0x2f81f7);
    for (let i = 0; i < 500; i += 1) {
      const totalNs = 1n + randomBelow(next, 10n * SECOND);
      const offsetNs = randomBelow(next, totalNs);
      const durationNs = randomBelow(next, totalNs - offsetNs + 1n);
      const { leftPercent, widthPercent } = barLayout({ offsetNs, durationNs }, totalNs);
      expect(leftPercent).toBeGreaterThanOrEqual(0);
      expect(widthPercent).toBeGreaterThanOrEqual(MIN_BAR_PERCENT);
      expect(widthPercent).toBeLessThanOrEqual(100);
      expect(leftPercent + widthPercent).toBeLessThanOrEqual(100 + 1e-9);
    }
  });
});

describe("traceExtentNs", () => {
  it("is zero without spans", () => {
    expect(traceExtentNs([])).toBe(0n);
  });

  it("ends at the latest end of the spans, not the latest start", () => {
    expect(
      traceExtentNs([
        { offsetNs: 0n, durationNs: 900n },
        { offsetNs: 100n, durationNs: 50n },
        { offsetNs: 800n, durationNs: 300n },
      ]),
    ).toBe(1_100n);
  });

  it("stays exact beyond the safe integer range", () => {
    const big = 2n ** 62n;
    expect(traceExtentNs([{ offsetNs: big, durationNs: 1n }])).toBe(big + 1n);
  });
});

describe("serviceColorIndex", () => {
  it("matches the FNV-1a offset basis for the empty name", () => {
    // FNV-1a of no bytes is 0x811c9dc5, whose low three bits are 5.
    expect(serviceColorIndex("")).toBe(5);
  });

  it("matches the published FNV-1a value for a single byte", () => {
    // FNV-1a of "a" is 0xe40c292c, whose low three bits are 4.
    expect(serviceColorIndex("a")).toBe(4);
  });

  it("is stable for the same name", () => {
    expect(serviceColorIndex("checkout")).toBe(serviceColorIndex("checkout"));
  });

  it("stays inside the palette for arbitrary names", () => {
    const next = randomSource(0x5eed);
    for (let i = 0; i < 300; i += 1) {
      const codePoints = Array.from({ length: 12 }, () => 0x20 + Math.floor(next() * 0x5e0));
      const name = String.fromCodePoint(...codePoints);
      const index = serviceColorIndex(name);
      expect(Number.isInteger(index)).toBe(true);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(index).toBeLessThan(SERVICE_PALETTE_SIZE);
    }
  });

  it("uses every palette colour across typical service names", () => {
    const names = Array.from({ length: 64 }, (_, i) => `service-${i}`);
    const used = new Set(names.map(serviceColorIndex));
    expect(used.size).toBe(SERVICE_PALETTE_SIZE);
  });
});

describe("serviceColor", () => {
  it("refers to a palette token", () => {
    expect(serviceColor("api")).toMatch(/^var\(--service-[0-7]\)$/);
  });

  it("gives the same colour to the same service", () => {
    expect(serviceColor("payments")).toBe(serviceColor("payments"));
  });
});

describe("timeScale", () => {
  it("has no ticks for a trace without duration", () => {
    expect(timeScale(0n)).toEqual([]);
  });

  it("places round ticks every 200 ms over one second", () => {
    expect(timeScale(SECOND)).toEqual(
      [0n, 200n, 400n, 600n, 800n, 1_000n].map((ms) => ({
        valueNs: ms * MS,
        percent: Number(ms) / 10,
      })),
    );
  });

  it("uses 5 ms steps for a trace of about 12 ms", () => {
    expect(timeScale(12_300_000n).map((tick) => tick.valueNs)).toEqual([
      0n,
      5n * MS,
      10n * MS,
    ]);
  });

  it("keeps ticks from zero to the total, in increasing order", () => {
    const next = randomSource(0xc0ffee);
    for (let i = 0; i < 300; i += 1) {
      const totalNs = MS + randomBelow(next, 100n * SECOND);
      const ticks = timeScale(totalNs);
      expect(ticks[0]?.valueNs).toBe(0n);
      expect(ticks.length).toBeGreaterThanOrEqual(2);
      expect(ticks.length).toBeLessThanOrEqual(7);
      for (let index = 1; index < ticks.length; index += 1) {
        const previous = ticks[index - 1];
        const current = ticks[index];
        expect(current).toBeDefined();
        expect(current?.valueNs).toBeGreaterThan(previous?.valueNs ?? 0n);
        expect(current?.valueNs).toBeLessThanOrEqual(totalNs);
      }
    }
  });

  it("ends at 100 percent when the total is a multiple of the step", () => {
    const ticks = timeScale(SECOND);
    expect(ticks.at(-1)).toEqual({ valueNs: SECOND, percent: 100 });
  });

  it("handles a one-nanosecond trace", () => {
    expect(timeScale(1n)).toEqual([
      { valueNs: 0n, percent: 0 },
      { valueNs: 1n, percent: 100 },
    ]);
  });
});
