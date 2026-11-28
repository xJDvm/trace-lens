import { describe, expect, it } from "vitest";

import type { ServiceMap } from "./api";
import { layoutServiceMap } from "./servicemap";

const WIDTH = 800;

const node = (service: string) => ({ service, calls: 1, errors: 0 });
const edge = (caller: string, callee: string) => ({ caller, callee, calls: 1, errors: 0 });

function graph(
  services: readonly string[],
  edges: readonly (readonly [string, string])[],
): ServiceMap {
  return {
    nodes: services.map(node),
    edges: edges.map(([caller, callee]) => edge(caller, callee)),
  };
}

function positionOf(map: ReturnType<typeof layoutServiceMap>, service: string) {
  const found = map.nodes.find((candidate) => candidate.service === service);
  if (found === undefined) {
    throw new Error(`no node for ${service}`);
  }
  return found;
}

/** A small deterministic generator, so that the random graphs are the same on every run. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

describe("layoutServiceMap", () => {
  it("gives an empty layout for an empty map", () => {
    expect(layoutServiceMap({ nodes: [], edges: [] }, WIDTH)).toEqual({ nodes: [], edges: [] });
  });

  it("places a single service in the centre", () => {
    const laid = layoutServiceMap(graph(["api"], []), WIDTH);
    expect(laid.nodes).toEqual([{ service: "api", x: WIDTH / 2, y: WIDTH / 2 }]);
    expect(laid.edges).toEqual([]);
  });

  it("puts each hop of a linear chain in its own column, left to right", () => {
    const laid = layoutServiceMap(
      graph(["gateway", "checkout", "payments"], [
        ["gateway", "checkout"],
        ["checkout", "payments"],
      ]),
      WIDTH,
    );
    const x = (service: string) => positionOf(laid, service).x;
    expect(x("gateway")).toBeLessThan(x("checkout"));
    expect(x("checkout")).toBeLessThan(x("payments"));
  });

  it("places a diamond with the join after both branches", () => {
    const laid = layoutServiceMap(
      graph(["a", "b", "c", "d"], [
        ["a", "b"],
        ["a", "c"],
        ["b", "d"],
        ["c", "d"],
      ]),
      WIDTH,
    );
    const x = (service: string) => positionOf(laid, service).x;
    expect(x("a")).toBeLessThan(x("b"));
    expect(x("b")).toBe(x("c"));
    expect(x("b")).toBeLessThan(x("d"));
    expect(positionOf(laid, "b").y).not.toBe(positionOf(laid, "c").y);
  });

  it("uses the longest path to set the layer of a service", () => {
    const laid = layoutServiceMap(
      graph(["a", "b", "c"], [
        ["a", "b"],
        ["b", "c"],
        ["a", "c"],
      ]),
      WIDTH,
    );
    expect(positionOf(laid, "c").x).toBe(WIDTH * 0.95);
  });

  it("terminates on a cycle and keeps both edges", () => {
    const laid = layoutServiceMap(
      graph(["a", "b"], [
        ["a", "b"],
        ["b", "a"],
      ]),
      WIDTH,
    );
    expect(laid.nodes).toHaveLength(2);
    expect(laid.edges.map((e) => `${e.caller}>${e.callee}`)).toEqual(["a>b", "b>a"]);
    expect(positionOf(laid, "a").x).toBeLessThan(positionOf(laid, "b").x);
  });

  it("terminates on a self-loop", () => {
    const laid = layoutServiceMap(graph(["a"], [["a", "a"]]), WIDTH);
    expect(laid.nodes).toEqual([{ service: "a", x: WIDTH / 2, y: WIDTH / 2 }]);
    expect(laid.edges).toHaveLength(1);
  });

  it("gives the same output for the same input", () => {
    const map = graph(["x", "y", "z", "w"], [
      ["x", "y"],
      ["y", "z"],
      ["z", "x"],
      ["w", "y"],
    ]);
    expect(layoutServiceMap(map, WIDTH)).toEqual(layoutServiceMap(map, WIDTH));
  });

  it("gives the same layout whatever the order of the nodes and edges", () => {
    const edges: (readonly [string, string])[] = [
      ["a", "b"],
      ["b", "c"],
      ["c", "a"],
      ["a", "d"],
    ];
    const forward = graph(["a", "b", "c", "d"], edges);
    const reversed = graph(["d", "c", "b", "a"], [...edges].reverse());
    expect(layoutServiceMap(reversed, WIDTH).nodes).toEqual(layoutServiceMap(forward, WIDTH).nodes);
  });

  it("keeps every coordinate within [0, width]", () => {
    const next = lcg(7);
    for (let round = 0; round < 50; round += 1) {
      const size = 1 + Math.floor(next() * 12);
      const services = Array.from({ length: size }, (_, index) => `s${index}`);
      const edges: (readonly [string, string])[] = [];
      for (let i = 0; i < size * 2; i += 1) {
        const from = services[Math.floor(next() * size)] ?? "s0";
        const to = services[Math.floor(next() * size)] ?? "s0";
        edges.push([from, to]);
      }
      const laid = layoutServiceMap(graph(services, edges), WIDTH);
      for (const { x, y } of laid.nodes) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThanOrEqual(WIDTH);
        expect(y).toBeGreaterThanOrEqual(0);
        expect(y).toBeLessThanOrEqual(WIDTH);
      }
    }
  });

  it("puts the services of a layer at distinct heights", () => {
    const laid = layoutServiceMap(
      graph(["hub", "a", "b", "c"], [
        ["hub", "a"],
        ["hub", "b"],
        ["hub", "c"],
      ]),
      WIDTH,
    );
    const heights = ["a", "b", "c"].map((service) => positionOf(laid, service).y);
    expect(new Set(heights).size).toBe(3);
    expect(Math.min(...heights)).toBe(WIDTH * 0.05);
    expect(Math.max(...heights)).toBe(WIDTH * 0.95);
  });

  it("lays out a service that appears only in an edge", () => {
    const laid = layoutServiceMap({ nodes: [], edges: [edge("a", "b")] }, WIDTH);
    expect(laid.nodes.map((n) => n.service)).toEqual(["a", "b"]);
    expect(laid.edges).toHaveLength(1);
  });

  it("gives a zero-width drawing with every node at the origin", () => {
    const laid = layoutServiceMap(graph(["a", "b"], [["a", "b"]]), 0);
    expect(laid.nodes).toEqual([
      { service: "a", x: 0, y: 0 },
      { service: "b", x: 0, y: 0 },
    ]);
  });

  it("draws each edge as a cubic curve between its endpoints", () => {
    const laid = layoutServiceMap(graph(["a", "b"], [["a", "b"]]), WIDTH);
    const a = positionOf(laid, "a");
    const b = positionOf(laid, "b");
    const middle = (a.x + b.x) / 2;
    expect(laid.edges[0]).toEqual({
      caller: "a",
      callee: "b",
      calls: 1,
      errors: 0,
      path: `M${a.x} ${a.y} C${middle} ${a.y} ${middle} ${b.y} ${b.x} ${b.y}`,
    });
  });

  it("keeps the call and error counts of the edges", () => {
    const map: ServiceMap = {
      nodes: [node("a"), node("b")],
      edges: [{ caller: "a", callee: "b", calls: 12, errors: 3 }],
    };
    const [laidEdge] = layoutServiceMap(map, WIDTH).edges;
    expect(laidEdge).toMatchObject({ calls: 12, errors: 3 });
  });

  it("rejects a negative or non-finite width", () => {
    const map = graph(["a"], []);
    expect(() => layoutServiceMap(map, -1)).toThrow(RangeError);
    expect(() => layoutServiceMap(map, Number.NaN)).toThrow(RangeError);
    expect(() => layoutServiceMap(map, Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});
