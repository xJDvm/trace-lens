/**
 * Pure layered layout for the service map: node positions and edge curves.
 *
 * A service sits one layer after the deepest of its callers, so calls flow from left to right
 * and each layer is a column. Cycles are broken first by a deterministic depth-first search: the
 * edges that close a cycle are left out of the layering, but they are still drawn. The drawing is
 * a square of side `width`, so both coordinates of every node lie in `[0, width]`.
 *
 * Service names are only data here: they are never interpreted as markup.
 */

import type { ServiceMap } from "./api";

/** A service placed in the drawing. */
export interface LaidOutNode {
  readonly service: string;
  readonly x: number;
  readonly y: number;
}

/** A call drawn as a cubic curve between the caller and the callee. */
export interface LaidOutEdge {
  readonly caller: string;
  readonly callee: string;
  readonly calls: number;
  readonly errors: number;
  /** SVG path data of the curve, from the caller's node to the callee's node. */
  readonly path: string;
}

/** The service map placed in a square drawing. */
export interface LaidOutMap {
  readonly nodes: readonly LaidOutNode[];
  readonly edges: readonly LaidOutEdge[];
}

/** Share of the width left empty on each side, so that nodes on the border stay visible. */
const MARGIN_FRACTION = 0.05;

/** Plain code-unit order, so that the layout does not depend on the locale. */
function byName(a: string, b: string): number {
  if (a < b) {
    return -1;
  }
  return a > b ? 1 : 0;
}

/** Position of `index` among `count` items spread evenly over the usable part of `width`. */
function spread(index: number, count: number, width: number): number {
  if (count === 1) {
    return width / 2;
  }
  const usable = width * (1 - 2 * MARGIN_FRACTION);
  return width * MARGIN_FRACTION + (usable * index) / (count - 1);
}

/**
 * Lays out the service map in a square drawing of side `width`.
 *
 * Nodes are ordered by name within each layer, and every node is placed exactly once, including
 * the services that appear only in edges. The result depends only on the content of `map`, not
 * on the order of its nodes.
 *
 * @param map - The services and the calls between them.
 * @param width - The side of the square drawing, in SVG user units.
 * @returns The positioned nodes, sorted by name, and the edges in the order of `map.edges`.
 * @throws {RangeError} When `width` is negative or not finite.
 */
export function layoutServiceMap(map: ServiceMap, width: number): LaidOutMap {
  if (!Number.isFinite(width) || width < 0) {
    throw new RangeError(`width must be a finite non-negative number, got ${width}`);
  }
  const named = [
    ...map.nodes.map((node) => node.service),
    ...map.edges.flatMap((edge) => [edge.caller, edge.callee]),
  ];
  const services = [...new Set(named)].sort(byName);
  if (services.length === 0) {
    return { nodes: [], edges: [] };
  }

  const layers = assignLayers(services, map);
  const layerCount = Math.max(...layers.values()) + 1;
  const members: string[][] = Array.from({ length: layerCount }, () => []);
  for (const service of services) {
    members[layers.get(service) ?? 0]?.push(service);
  }

  const positions = new Map<string, { readonly x: number; readonly y: number }>();
  for (const [layer, column] of members.entries()) {
    const x = spread(layer, layerCount, width);
    column.forEach((service, row) => {
      positions.set(service, { x, y: spread(row, column.length, width) });
    });
  }

  const nodes = services.map((service) => {
    const { x, y } = positions.get(service) ?? { x: 0, y: 0 };
    return { service, x, y };
  });
  const edges: LaidOutEdge[] = [];
  for (const edge of map.edges) {
    const from = positions.get(edge.caller);
    const to = positions.get(edge.callee);
    if (from !== undefined && to !== undefined) {
      edges.push({ ...edge, path: curvePath(from, to) });
    }
  }
  return { nodes, edges };
}

/**
 * The layer of every service: the longest path from a service without incoming edges.
 *
 * The edges closing a cycle are found by a depth-first search from the services in name order,
 * exploring callees in name order. An edge to a service still on the search stack closes a cycle
 * and is left out, so the remaining edges form a DAG.
 *
 * @param services - Every service, sorted by name.
 * @param map - The calls between the services.
 */
function assignLayers(services: readonly string[], map: ServiceMap): Map<string, number> {
  const callees = new Map<string, string[]>(services.map((service) => [service, []]));
  for (const edge of map.edges) {
    callees.get(edge.caller)?.push(edge.callee);
  }
  for (const list of callees.values()) {
    list.sort(byName);
  }

  const dagCallees = new Map<string, string[]>(services.map((service) => [service, []]));
  const incoming = new Map<string, number>(services.map((service) => [service, 0]));
  const visited = new Set<string>();
  const onStack = new Set<string>();
  for (const root of services) {
    if (visited.has(root)) {
      continue;
    }
    visited.add(root);
    onStack.add(root);
    const stack = [{ service: root, next: 0 }];
    for (let top = stack.at(-1); top !== undefined; top = stack.at(-1)) {
      const callee = callees.get(top.service)?.[top.next];
      if (callee === undefined) {
        onStack.delete(top.service);
        stack.pop();
        continue;
      }
      top.next += 1;
      if (onStack.has(callee)) {
        continue;
      }
      dagCallees.get(top.service)?.push(callee);
      incoming.set(callee, (incoming.get(callee) ?? 0) + 1);
      if (!visited.has(callee)) {
        visited.add(callee);
        onStack.add(callee);
        stack.push({ service: callee, next: 0 });
      }
    }
  }

  const layers = new Map<string, number>(services.map((service) => [service, 0]));
  const pending = new Map(incoming);
  const ready = services.filter((service) => incoming.get(service) === 0);
  for (const service of ready) {
    const layer = layers.get(service) ?? 0;
    for (const callee of dagCallees.get(service) ?? []) {
      layers.set(callee, Math.max(layers.get(callee) ?? 0, layer + 1));
      const left = (pending.get(callee) ?? 0) - 1;
      pending.set(callee, left);
      if (left === 0) {
        ready.push(callee);
      }
    }
  }
  return layers;
}

/**
 * A cubic curve from `from` to `to`, leaving and entering horizontally so that the curve reads
 * as a flow from left to right.
 */
function curvePath(
  from: { readonly x: number; readonly y: number },
  to: { readonly x: number; readonly y: number },
): string {
  const middle = (from.x + to.x) / 2;
  return `M${from.x} ${from.y} C${middle} ${from.y} ${middle} ${to.y} ${to.x} ${to.y}`;
}
