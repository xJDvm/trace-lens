import { useEffect, useState } from "react";

import {
  fetchServices,
  fetchTraces,
  nextCursor,
  type TraceCursor,
  type TraceFilters,
  type TraceSummary,
} from "../api";
import { EMPTY_FILTER_TEXT, parseFilters, type FilterText } from "../filters";
import { durationPercent, formatDuration, formatRelativeTime } from "../format";
import { latencyHash, traceHash } from "../route";

/** A page to load: the first page of a filter set, or the page after `cursor` when appending. */
interface PageRequest {
  readonly filters: TraceFilters;
  readonly cursor: TraceCursor | null;
  readonly append: boolean;
}

interface ListState {
  readonly traces: readonly TraceSummary[];
  readonly cursor: TraceCursor | null;
}

const INITIAL_FILTERS = parseFilters(EMPTY_FILTER_TEXT);
const NANOSECONDS_PER_MS = 1_000_000n;

/**
 * The trace list with its filters: service, duration range and error status. Each row shows the
 * root operation and a duration bar scaled to the longest trace loaded so far.
 */
export function TraceList() {
  const [text, setText] = useState<FilterText>(EMPTY_FILTER_TEXT);
  const [request, setRequest] = useState<PageRequest>({
    filters: INITIAL_FILTERS,
    cursor: null,
    append: false,
  });
  const [services, setServices] = useState<readonly string[]>([]);
  const [servicesError, setServicesError] = useState<string | null>(null);
  const [list, setList] = useState<ListState>({ traces: [], cursor: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    const controller = new AbortController();
    setLoading(true);
    fetchTraces(request.filters, request.cursor, controller.signal)
      .then((page) => {
        setList((previous) => ({
          traces: request.append ? [...previous.traces, ...page.traces] : page.traces,
          cursor: nextCursor(page),
        }));
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(messageOf(caught));
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [request]);

  const updateText = (next: FilterText) => {
    setText(next);
    setRequest({ filters: parseFilters(next), cursor: null, append: false });
  };

  const loadMore = () => {
    if (list.cursor !== null) {
      setRequest({ filters: request.filters, cursor: list.cursor, append: true });
    }
  };

  const { traces } = list;
  const longest = traces.reduce(
    (max, trace) => (BigInt(trace.durationNs) > max ? BigInt(trace.durationNs) : max),
    0n,
  );
  const now = Date.now();
  const message = servicesError ?? error;

  return (
    <section className="trace-list" aria-labelledby="trace-list-title">
      <h2 id="trace-list-title">Traces</h2>

      <div className="filters" role="group" aria-label="Trace filters">
        <label>
          <span>Service</span>
          <select
            value={text.service}
            onChange={(event) => {
              updateText({ ...text, service: event.target.value });
            }}
          >
            <option value="">All services</option>
            {services.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Min duration (ms)</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={text.minMs}
            onChange={(event) => {
              updateText({ ...text, minMs: event.target.value });
            }}
          />
        </label>
        <label>
          <span>Max duration (ms)</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={text.maxMs}
            onChange={(event) => {
              updateText({ ...text, maxMs: event.target.value });
            }}
          />
        </label>
        <label>
          <span>Status</span>
          <select
            value={text.error}
            onChange={(event) => {
              updateText({ ...text, error: event.target.value as FilterText["error"] });
            }}
          >
            <option value="">All traces</option>
            <option value="true">With errors</option>
            <option value="false">Without errors</option>
          </select>
        </label>
      </div>

      <a className="latency-link" href={latencyHash(text.service)}>
        Latency and histogram
      </a>

      {message !== null && (
        <p className="message message-error" role="alert">
          {message}
        </p>
      )}

      {traces.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Started</th>
                <th scope="col">Root</th>
                <th scope="col">Duration</th>
                <th scope="col">Spans</th>
                <th scope="col">Errors</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => {
                const started = BigInt(trace.startNs);
                const duration = BigInt(trace.durationNs);
                const startedIso = new Date(Number(started / NANOSECONDS_PER_MS)).toISOString();
                return (
                  <tr key={trace.traceId} data-testid="trace-row">
                    <td data-label="Started">
                      <time dateTime={startedIso}>{formatRelativeTime(started, now)}</time>
                    </td>
                    <td data-label="Root">
                      <a className="trace-link" href={traceHash(trace.traceId)}>
                        <span className="root-service">{trace.rootService}</span>{" "}
                        <span className="root-name">{trace.rootName}</span>
                        <span className="trace-id" title={trace.traceId}>
                          {trace.traceId.slice(0, 8)}
                        </span>
                      </a>
                    </td>
                    <td data-label="Duration">
                      <div className="duration">
                        <span className="bar-track" aria-hidden="true">
                          <span
                            className="bar"
                            style={{ width: `${durationPercent(duration, longest)}%` }}
                          />
                        </span>
                        <span className="duration-text">{formatDuration(duration)}</span>
                      </div>
                    </td>
                    <td data-label="Spans">{trace.spanCount}</td>
                    <td data-label="Errors">
                      {trace.errorCount > 0 ? (
                        <span className="badge badge-error">{trace.errorCount}</span>
                      ) : (
                        "0"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {loading && (
        <p className="message" role="status">
          Loading traces…
        </p>
      )}
      {!loading && error === null && traces.length === 0 && (
        <p className="message">No traces match these filters.</p>
      )}

      {list.cursor !== null && (
        <div className="actions">
          <button type="button" onClick={loadMore} disabled={loading}>
            Load more
          </button>
        </div>
      )}
    </section>
  );
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}
