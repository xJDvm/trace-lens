import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  fetchServiceMap,
  type ServiceMap as ServiceMapData,
  type ServiceMapNode,
} from "../api";
import { layoutServiceMap, type LaidOutEdge, type LaidOutNode } from "../servicemap";
import { latencyHash } from "../route";
import { serviceColor } from "../waterfall";
import {
  edgeStrokeWidth,
  errorRate,
  formatErrorRate,
  truncateLabel,
} from "../servicemapview";

/** Side of the square drawing, in SVG user units. The drawing scales to its container. */
const DRAWING_SIZE = 900;
/** Size of a service box, in SVG user units. */
const NODE_WIDTH = 150;
const NODE_HEIGHT = 52;
/** Longest service name drawn in a box; the full name is in the tooltip. */
const MAX_LABEL_CHARS = 16;
/** Vertical offsets of the name and the error rate inside a box. */
const NAME_BASELINE = -4;
const RATE_BASELINE = 14;

/**
 * The service map: one box per service, placed by {@link layoutServiceMap}, and one curve per
 * call between two services. Edges are thicker for more calls and red when some call failed.
 * Clicking a service opens its latency view.
 */
export function ServiceMap() {
  const [map, setMap] = useState<ServiceMapData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchServiceMap(controller.signal)
      .then((loaded) => {
        setMap(loaded);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(messageOf(caught));
        }
      });
    return () => {
      controller.abort();
    };
  }, []);

  let body: ReactNode;
  if (error !== null) {
    body = (
      <p className="message message-error" role="alert">
        {error}
      </p>
    );
  } else if (map === null) {
    body = (
      <p className="message" role="status">
        Loading service map…
      </p>
    );
  } else if (map.nodes.length === 0) {
    body = <p className="message">No services have reported spans yet.</p>;
  } else {
    body = (
      <>
        <p className="message">
          Click a service to see its latency. Thicker edges carry more calls; red edges had errors.
        </p>
        <MapDrawing map={map} />
      </>
    );
  }

  return (
    <section className="service-map" aria-labelledby="service-map-title">
      <h2 id="service-map-title">Service map</h2>
      {body}
    </section>
  );
}

interface MapDrawingProps {
  readonly map: ServiceMapData;
}

/** The SVG drawing of a non-empty service map. */
function MapDrawing({ map }: MapDrawingProps) {
  const laidOut = useMemo(() => layoutServiceMap(map, DRAWING_SIZE), [map]);
  const nodeStats = useMemo(
    () => new Map(map.nodes.map((node) => [node.service, node])),
    [map],
  );
  const maxCalls = useMemo(
    () => map.edges.reduce((max, edge) => Math.max(max, edge.calls), 0),
    [map],
  );

  return (
    <div className="service-map-scroll">
      <svg
        className="service-map-chart"
        viewBox={`0 0 ${DRAWING_SIZE} ${DRAWING_SIZE}`}
        role="group"
        aria-label="Services and the calls between them"
      >
        <g>
          {laidOut.edges.map((edge) => (
            <MapEdge
              key={JSON.stringify([edge.caller, edge.callee])}
              edge={edge}
              maxCalls={maxCalls}
            />
          ))}
        </g>
        <g>
          {laidOut.nodes.map((node) => (
            <MapNode key={node.service} node={node} stats={nodeStats.get(node.service)} />
          ))}
        </g>
      </svg>
    </div>
  );
}

interface MapEdgeProps {
  readonly edge: LaidOutEdge;
  readonly maxCalls: number;
}

/** A call between two services, drawn as a curve with a tooltip of its counts. */
function MapEdge({ edge, maxCalls }: MapEdgeProps) {
  const className = edge.errors > 0 ? "map-edge map-edge-error" : "map-edge";
  return (
    <path
      className={className}
      d={edge.path}
      strokeWidth={edgeStrokeWidth(edge.calls, maxCalls)}
    >
      <title>{`${edge.caller} → ${edge.callee}: ${edge.calls} calls, ${edge.errors} errors`}</title>
    </path>
  );
}

interface MapNodeProps {
  readonly node: LaidOutNode;
  /** The counts of the service; `undefined` when the map does not describe it. */
  readonly stats: ServiceMapNode | undefined;
}

/** A service: a box with its name and error rate, linked to its latency view. */
function MapNode({ node, stats }: MapNodeProps) {
  const calls = stats?.calls ?? 0;
  const errors = stats?.errors ?? 0;
  const rate = errorRate(calls, errors);
  const rateClass = errors > 0 ? "map-node-rate map-node-rate-error" : "map-node-rate";
  return (
    <a className="map-node" href={latencyHash(node.service)}>
      <title>{`${node.service}: ${calls} incoming calls, ${errors} errors`}</title>
      <rect
        className="map-node-box"
        x={node.x - NODE_WIDTH / 2}
        y={node.y - NODE_HEIGHT / 2}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={8}
        style={{ stroke: serviceColor(node.service) }}
      />
      <text className="map-node-name" x={node.x} y={node.y + NAME_BASELINE} textAnchor="middle">
        {truncateLabel(node.service, MAX_LABEL_CHARS)}
      </text>
      <text className={rateClass} x={node.x} y={node.y + RATE_BASELINE} textAnchor="middle">
        {formatErrorRate(rate)}
      </text>
    </a>
  );
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}
