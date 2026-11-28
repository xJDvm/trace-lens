import { describe, expect, it } from "vitest";

import type { SpanRow } from "./api";
import { flameFrames, type Frame } from "./flame";

interface SpanSpec {
  readonly id: string;
  readonly parent?: string | null;
  readonly offsetNs?: number;
  readonly durationNs?: number;
  readonly service?: string;
  readonly name?: string;
  readonly statusCode?: number;
}

/** A span row as the API sends it, with the fields the flame graph does not read set to defaults. */
function span(spec: SpanSpec): SpanRow {
  const offsetNs = spec.offsetNs ?? 0;
  const durationNs = spec.durationNs ?? 10;
  return {
    traceId: "0".repeat(32),
    spanId: spec.id,
    parentSpanId: spec.parent ?? null,
    service: spec.service ?? "svc",
    name: spec.name ?? spec.id,
    kind: 1,
    startNs: String(offsetNs),
    endNs: String(offsetNs + durationNs),
    durationNs: String(durationNs),
    statusCode: spec.statusCode ?? 0,
    statusMessage: "",
    attributes: [],
    depth: 0,
    offsetNs: String(offsetNs),
  };
}

/** The frame of a span, failing the test when the span is missing from the output. */
function frameOf(frames: readonly Frame[], spanId: string): Frame {
  const frame = frames.find((candidate) => candidate.spanId === spanId);
  if (frame === undefined) {
    throw new Error(`no frame for ${spanId}`);
  }
  return frame;
}

describe("flameFrames", () => {
  it("returns no frames for an empty trace", () => {
    expect(flameFrames([])).toEqual([]);
  });

  it("places a single root across the whole trace", () => {
    const frames = flameFrames([span({ id: "a", durationNs: 1_000 })]);
    expect(frames).toEqual([
      {
        spanId: "a",
        depth: 0,
        x0: 0,
        x1: 1,
        label: "a",
        service: "svc",
        isError: false,
      },
    ]);
  });

  it("gives every span of a zero-length trace an empty frame at the start", () => {
    const frames = flameFrames([
      span({ id: "a", durationNs: 0 }),
      span({ id: "b", parent: "a", durationNs: 0 }),
    ]);
    expect(frames.map((frame) => [frame.x0, frame.x1])).toEqual([
      [0, 0],
      [0, 0],
    ]);
  });

  it("sets the depth of each span from its ancestors", () => {
    const frames = flameFrames([
      span({ id: "root", durationNs: 1_000 }),
      span({ id: "child", parent: "root", durationNs: 500 }),
      span({ id: "grandchild", parent: "child", durationNs: 100 }),
      span({ id: "sibling", parent: "root", offsetNs: 600, durationNs: 100 }),
    ]);
    expect(frameOf(frames, "root").depth).toBe(0);
    expect(frameOf(frames, "child").depth).toBe(1);
    expect(frameOf(frames, "sibling").depth).toBe(1);
    expect(frameOf(frames, "grandchild").depth).toBe(2);
  });

  it("emits every parent before its children, in start order", () => {
    const frames = flameFrames([
      span({ id: "grandchild", parent: "child", durationNs: 100 }),
      span({ id: "late", parent: "root", offsetNs: 600, durationNs: 100 }),
      span({ id: "child", parent: "root", durationNs: 500 }),
      span({ id: "root", durationNs: 1_000 }),
    ]);
    expect(frames.map((frame) => frame.spanId)).toEqual([
      "root",
      "child",
      "grandchild",
      "late",
    ]);
  });

  it("scales the horizontal extent to the trace's time range", () => {
    const frames = flameFrames([
      span({ id: "root", durationNs: 800 }),
      span({ id: "child", parent: "root", offsetNs: 200, durationNs: 200 }),
    ]);
    const child = frameOf(frames, "child");
    expect(child.x0).toBeCloseTo(0.25, 8);
    expect(child.x1).toBeCloseTo(0.5, 8);
  });

  it("clips a child to the time range of its parent", () => {
    const frames = flameFrames([
      span({ id: "root", offsetNs: 100, durationNs: 100 }),
      // Starts before the parent and ends after it.
      span({ id: "early", parent: "root", offsetNs: 50, durationNs: 100 }),
      span({ id: "late", parent: "root", offsetNs: 150, durationNs: 200 }),
    ]);
    // The trace runs from 0 to 350 ns, the end of the unclipped "late" span.
    const root = frameOf(frames, "root");
    const early = frameOf(frames, "early");
    const late = frameOf(frames, "late");
    expect(root.x0).toBeCloseTo(100 / 350, 8);
    expect(root.x1).toBeCloseTo(200 / 350, 8);
    expect(early.x0).toBe(root.x0);
    expect(early.x1).toBeCloseTo(150 / 350, 8);
    expect(late.x0).toBeCloseTo(150 / 350, 8);
    expect(late.x1).toBe(root.x1);
  });

  it("clips a grandchild to the clipped frame of its parent", () => {
    const frames = flameFrames([
      span({ id: "root", durationNs: 1_000 }),
      span({ id: "child", parent: "root", offsetNs: 400, durationNs: 100 }),
      // Ends after the child, so it is clipped by the child and not by the root.
      span({
        id: "grandchild",
        parent: "child",
        offsetNs: 450,
        durationNs: 500,
      }),
    ]);
    const child = frameOf(frames, "child");
    const grandchild = frameOf(frames, "grandchild");
    expect(grandchild.x0).toBeCloseTo(0.45, 8);
    expect(grandchild.x1).toBeCloseTo(child.x1, 8);
  });

  it("collapses a child that lies outside its parent to the parent's edge", () => {
    const frames = flameFrames([
      span({ id: "root", durationNs: 100 }),
      span({ id: "outside", parent: "root", offsetNs: 500, durationNs: 100 }),
    ]);
    const root = frameOf(frames, "root");
    const outside = frameOf(frames, "outside");
    expect(outside.x0).toBe(root.x1);
    expect(outside.x1).toBe(root.x1);
  });

  it("makes orphan spans extra roots at depth zero", () => {
    const frames = flameFrames([
      span({ id: "root", durationNs: 1_000 }),
      span({ id: "orphan", parent: "missing", offsetNs: 100, durationNs: 50 }),
      span({
        id: "orphan-child",
        parent: "orphan",
        offsetNs: 100,
        durationNs: 10,
      }),
    ]);
    expect(frameOf(frames, "orphan").depth).toBe(0);
    expect(frameOf(frames, "orphan-child").depth).toBe(1);
    expect(frames).toHaveLength(3);
  });

  it("includes spans on a parent cycle exactly once", () => {
    const frames = flameFrames([
      span({ id: "a", parent: "b", durationNs: 100 }),
      span({ id: "b", parent: "a", durationNs: 100 }),
      span({ id: "self", parent: "self", durationNs: 100 }),
    ]);
    expect(frames.map((frame) => frame.spanId).sort()).toEqual([
      "a",
      "b",
      "self",
    ]);
    expect(frames.map((frame) => frame.depth)).toEqual([0, 1, 0]);
  });

  it("carries the service, label and error status of each span", () => {
    const frames = flameFrames([
      span({ id: "s1", service: "checkout", name: "POST /pay", statusCode: 2 }),
      span({
        id: "s2",
        parent: "s1",
        service: "db",
        name: "INSERT",
        statusCode: 1,
      }),
    ]);
    expect(frameOf(frames, "s1")).toMatchObject({
      label: "POST /pay",
      service: "checkout",
      isError: true,
    });
    expect(frameOf(frames, "s2")).toMatchObject({
      label: "INSERT",
      service: "db",
      isError: false,
    });
  });

  it("gives the same frames whatever the order of the input", () => {
    const spans = [
      span({ id: "root", durationNs: 1_000 }),
      span({ id: "x", parent: "root", offsetNs: 100, durationNs: 300 }),
      span({ id: "y", parent: "root", offsetNs: 100, durationNs: 200 }),
      span({ id: "z", parent: "x", offsetNs: 150, durationNs: 50 }),
    ];
    expect(flameFrames([...spans].reverse())).toEqual(flameFrames(spans));
  });

  it("keeps every child inside its parent on seeded random trees", () => {
    const next = seededRandom(0x2f6e2b1);
    for (let trial = 0; trial < 200; trial += 1) {
      const count = 1 + Math.floor(next() * 30);
      const spans: SpanRow[] = [];
      for (let index = 0; index < count; index += 1) {
        const parent =
          index === 0 || next() < 0.1 ? null : `s${Math.floor(next() * index)}`;
        spans.push(
          span({
            id: `s${index}`,
            parent,
            offsetNs: Math.floor(next() * 1_000),
            durationNs: Math.floor(next() * 500),
          }),
        );
      }
      const frames = flameFrames(spans);
      expect(frames).toHaveLength(count);
      const framesById = new Map(frames.map((frame) => [frame.spanId, frame]));
      for (const row of spans) {
        const frame = framesById.get(row.spanId);
        expect(frame).toBeDefined();
        if (frame === undefined) {
          continue;
        }
        expect(frame.x0).toBeGreaterThanOrEqual(0);
        expect(frame.x1).toBeLessThanOrEqual(1);
        expect(frame.x0).toBeLessThanOrEqual(frame.x1);
        // Every parent precedes its child in the generator, so each non-root has a parent frame.
        if (row.parentSpanId !== null) {
          const parent = framesById.get(row.parentSpanId);
          expect(parent).toBeDefined();
          if (parent !== undefined) {
            expect(frame.depth).toBe(parent.depth + 1);
            expect(frame.x0).toBeGreaterThanOrEqual(parent.x0);
            expect(frame.x1).toBeLessThanOrEqual(parent.x1);
          }
        }
      }
    }
  });
});

/** A deterministic pseudo-random source in `[0, 1)` (xorshift32), so the random cases are reproducible. */
function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x1_0000_0000;
  };
}
