import { describe, expect, it } from "vitest";

import { frameBox, frameLabel, MIN_FRAME_PX, MIN_LABEL_PX } from "./flameview";

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

describe("frameBox", () => {
  it("places the frame by its fractions of the drawing width", () => {
    expect(frameBox({ x0: 0.25, x1: 0.75 }, 800)).toEqual({ xPx: 200, widthPx: 400 });
  });

  it("keeps a frame of no extent visible at the minimum width", () => {
    expect(frameBox({ x0: 0.5, x1: 0.5 }, 800)).toEqual({ xPx: 400, widthPx: MIN_FRAME_PX });
  });

  it("never returns a width below the minimum, for any frame in the trace", () => {
    const random = randomSource(7);
    for (let index = 0; index < 500; index += 1) {
      const x0 = random();
      const x1 = x0 + (1 - x0) * random();
      const box = frameBox({ x0, x1 }, 1000);
      expect(box.widthPx).toBeGreaterThanOrEqual(MIN_FRAME_PX);
      expect(box.xPx).toBeGreaterThanOrEqual(0);
      expect(box.xPx + box.widthPx).toBeLessThanOrEqual(1000 + MIN_FRAME_PX);
    }
  });
});

describe("frameLabel", () => {
  it("gives no label to a frame narrower than the threshold", () => {
    expect(frameLabel("checkout", 0)).toBe("");
    expect(frameLabel("checkout", 1)).toBe("");
    expect(frameLabel("checkout", MIN_LABEL_PX - 0.5)).toBe("");
  });

  it("gives no label when the width is not a number", () => {
    expect(frameLabel("checkout", Number.NaN)).toBe("");
  });

  it("shows the whole name when it fits", () => {
    expect(frameLabel("GET", 400)).toBe("GET");
  });

  it("truncates a name to the characters that fit at the threshold", () => {
    // (40 - 8) / 7 = 4 characters, the last one an ellipsis.
    expect(frameLabel("checkout-service", MIN_LABEL_PX)).toBe("che…");
  });

  it("truncates with an ellipsis, never longer than the frame allows", () => {
    const label = "POST /api/orders/checkout";
    for (let width = MIN_LABEL_PX; width <= 300; width += 3) {
      const text = frameLabel(label, width);
      const budget = Math.floor((width - 8) / 7);
      expect(Array.from(text).length).toBeLessThanOrEqual(budget);
      expect(text === label || text.endsWith("…")).toBe(true);
    }
  });
});
