import { useEffect, useState } from "react";

import { fetchLatency, fetchServices, type LatencyStats } from "../api";
import { formatOptionalDuration } from "../format";
import { histogramScale } from "../histogram";
import { latencyHash } from "../route";

/** Width of the histogram in SVG user units; the drawing scales to the width of its container. */
const VIEW_WIDTH = 500;
/** Horizontal inset of the plot, so that the edge labels are not cut off. */
const PAD_X = 24;
const PLOT_WIDTH = VIEW_WIDTH - 2 * PAD_X;
const VIEW_HEIGHT = 180;
/** Height reserved under the plot for the axis labels. */
const AXIS_HEIGHT = 22;
const PLOT_HEIGHT = VIEW_HEIGHT - AXIS_HEIGHT;
/** Share of each bucket's slot that the bar fills; the rest is the gap between bars. */
const BAR_FILL = 0.8;
/** An axis label is drawn for every this many buckets. */
const LABEL_EVERY = 4;

interface LatencyViewProps {
  /** The service to show, or `null` when the URL does not name one. */
  readonly service: string | null;
}

/** The outcome of loading the statistics of one service. */
interface Loaded {
  readonly service: string;
  readonly stats: LatencyStats | null;
  readonly error: string | null;
}

/**
 * The latency view of one service: p50, p95 and p99 tiles and a histogram of the most recent
 * span durations. The service is chosen with a selector, which also updates the URL hash.
 */
export function LatencyView({ service }: LatencyViewProps) {
  const [services, setServices] = useState<readonly string[]>([]);
  const [servicesError, setServicesError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchServices(controller.signal)
      .then((names) => {
        setServices(names);
        setServicesError(null);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setServicesError(messageOf(caught));
        }
      });
    return () => {
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (service === null) {
      return;
    }
    const controller = new AbortController();
    fetchLatency(service, controller.signal)
      .then((stats) => {
        setLoaded({ service, stats, error: null });
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setLoaded({ service, stats: null, error: messageOf(caught) });
        }
      });
    return () => {
      controller.abort();
    };
  }, [service]);

  // Statistics of a previous service are not shown for the current one while it loads.
  const current = loaded !== null && loaded.service === service ? loaded : null;
  // A service named by the URL stays selectable even when the service list has not loaded it.
  const options =
    service !== null && !services.includes(service) ? [service, ...services] : services;
  const message = servicesError ?? current?.error ?? null;

  return (
    <section className="latency-view" aria-labelledby="latency-title">
      <a className="back-link" href="#/">
        ← Traces
      </a>
      <h2 id="latency-title">Latency</h2>

      <div className="latency-controls">
        <label>
          <span>Service</span>
          <select
            value={service ?? ""}
            onChange={(event) => {
              window.location.hash = latencyHash(event.target.value);
            }}
          >
            <option value="" disabled>
              Choose a service
            </option>
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {message !== null && (
        <p className="message message-error" role="alert">
          {message}
        </p>
      )}

      {service === null && <p className="message">Choose a service to see its latency.</p>}
      {service !== null && current === null && (
        <p className="message" role="status">
          Loading latency…
        </p>
      )}
      {current?.stats && <LatencyStatsView service={current.service} stats={current.stats} />}
    </section>
  );
}

interface LatencyStatsViewProps {
  readonly service: string;
  readonly stats: LatencyStats;
}

function LatencyStatsView({ service, stats }: LatencyStatsViewProps) {
  const tiles: readonly (readonly [string, string | null])[] = [
    ["p50", stats.p50],
    ["p95", stats.p95],
    ["p99", stats.p99],
  ];

  return (
    <>
      <dl className="latency-tiles">
        {tiles.map(([label, value]) => (
          <div className="latency-tile" key={label}>
            <dt>{label}</dt>
            <dd>{formatOptionalDuration(value)}</dd>
          </div>
        ))}
      </dl>
      {stats.count === 0 ? (
        <p className="message">No spans recorded for this service yet.</p>
      ) : (
        <>
          <p className="message">Based on the last {stats.count} spans.</p>
          <Histogram service={service} stats={stats} />
        </>
      )}
    </>
  );
}

interface HistogramProps {
  readonly service: string;
  readonly stats: LatencyStats;
}

/** The latency histogram as an SVG: one bar per bucket, labelled by its upper edge. */
function Histogram({ service, stats }: HistogramProps) {
  const { bars } = histogramScale(stats.histogram);
  const slot = PLOT_WIDTH / Math.max(bars.length, 1);
  const barWidth = slot * BAR_FILL;

  return (
    <svg
      className="latency-chart"
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      role="img"
      aria-label={`Latency histogram of ${service}, ${stats.count} spans`}
    >
      <line
        className="hist-axis"
        x1={PAD_X}
        x2={VIEW_WIDTH - PAD_X}
        y1={PLOT_HEIGHT}
        y2={PLOT_HEIGHT}
      />
      {bars.map((bar, index) => {
        const height = (bar.heightPercent / 100) * PLOT_HEIGHT;
        return (
          <rect
            key={index}
            className="hist-bar"
            x={PAD_X + index * slot + (slot - barWidth) / 2}
            y={PLOT_HEIGHT - height}
            width={barWidth}
            height={height}
          >
            <title>{`${bar.label}: ${bar.count}`}</title>
          </rect>
        );
      })}
      {bars.map((bar, index) =>
        index % LABEL_EVERY === 0 ? (
          <text
            key={index}
            className="hist-label"
            x={PAD_X + index * slot + slot / 2}
            y={VIEW_HEIGHT - 6}
            textAnchor="middle"
          >
            {bar.label}
          </text>
        ) : null,
      )}
    </svg>
  );
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}
