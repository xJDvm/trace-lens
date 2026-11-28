import { useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchTrace, type SpanAttribute, type SpanRow, type TraceDetail } from "../api";
import { attributeText, formatDuration, statusLabel } from "../format";
import { FlameGraph } from "./FlameGraph";
import {
  barLayout,
  serviceColor,
  timeScale,
  traceExtentNs,
  type Extent,
  type ScaleTick,
} from "../waterfall";

/** `StatusCode` of an OpenTelemetry span that ended in error. */
const STATUS_ERROR = 2;
/** Indentation per tree level, in pixels, and the level after which indentation stops growing. */
const INDENT_PX = 12;
const MAX_INDENT_LEVELS = 12;

/** The two views of a trace. */
type TraceTab = "waterfall" | "flame";

/** The tabs above the trace body, in display order. */
const TRACE_TABS: readonly { readonly tab: TraceTab; readonly label: string }[] = [
  { tab: "waterfall", label: "Waterfall" },
  { tab: "flame", label: "Flame graph" },
];

interface TraceViewProps {
  /** The 32-character hex id of the trace to show. */
  readonly traceId: string;
}

/**
 * The waterfall page of one trace: a row per span, indented by depth, with a bar on a shared
 * time scale. Selecting a row shows the span's details; the first span is selected at first.
 */
export function TraceView({ traceId }: TraceViewProps) {
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchTrace(traceId, controller.signal)
      .then((detail) => {
        setTrace(detail);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Unexpected error");
        }
      });
    return () => {
      controller.abort();
    };
  }, [traceId]);

  let body: ReactNode;
  if (trace !== null) {
    body = <TraceContent trace={trace} />;
  } else if (error !== null) {
    body = (
      <p className="message message-error" role="alert">
        {error}
      </p>
    );
  } else {
    body = (
      <p className="message" role="status">
        Loading trace…
      </p>
    );
  }

  return (
    <section className="trace-view" aria-label="Trace">
      <a className="back-link" href="#/">
        ← Traces
      </a>
      {body}
    </section>
  );
}

interface TraceContentProps {
  readonly trace: TraceDetail;
}

function TraceContent({ trace }: TraceContentProps) {
  const [selected, setSelected] = useState(0);
  const [tab, setTab] = useState<TraceTab>("waterfall");
  const totalNs = useMemo(() => traceExtentNs(trace.rows.map(rowExtent)), [trace.rows]);
  const ticks = useMemo(() => timeScale(totalNs), [totalNs]);
  const services = new Set(trace.rows.map((row) => row.service));
  const chosen = trace.rows[selected];
  const { summary } = trace;

  return (
    <>
      <header className="trace-header">
        <h2>
          Trace <span className="trace-id-full">{summary.traceId}</span>
        </h2>
        <p className="trace-meta">
          <span>{formatDuration(BigInt(summary.durationNs))}</span>
          <span>{summary.spanCount} spans</span>
          <span>
            {services.size} {services.size === 1 ? "service" : "services"}
          </span>
          {summary.errorCount > 0 && (
            <span className="badge badge-error">{summary.errorCount} errors</span>
          )}
          {trace.orphans > 0 && <span>{trace.orphans} orphan spans</span>}
        </p>
      </header>

      <div className="view-tabs" role="group" aria-label="View">
        {TRACE_TABS.map(({ tab: value, label }) => (
          <button
            key={value}
            type="button"
            className="view-tab"
            aria-pressed={tab === value}
            onClick={() => {
              setTab(value);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="trace-body">
        {tab === "waterfall" ? (
          <>
            <div className="waterfall" role="group" aria-label="Spans">
              <div className="wf-grid wf-head" aria-hidden="true">
                <span>Span</span>
                <Scale ticks={ticks} />
              </div>
              <ol className="wf-rows">
                {trace.rows.map((row, index) => (
                  <WaterfallRow
                    key={`${row.traceId}-${row.spanId}`}
                    row={row}
                    totalNs={totalNs}
                    selected={index === selected}
                    onSelect={() => {
                      setSelected(index);
                    }}
                  />
                ))}
              </ol>
            </div>

            {chosen !== undefined && <SpanDetails row={chosen} />}
          </>
        ) : (
          <FlameGraph spans={trace.rows} />
        )}
      </div>
    </>
  );
}

interface WaterfallRowProps {
  readonly row: SpanRow;
  readonly totalNs: bigint;
  readonly selected: boolean;
  readonly onSelect: () => void;
}

function WaterfallRow({ row, totalNs, selected, onSelect }: WaterfallRowProps) {
  const failed = row.statusCode === STATUS_ERROR;
  const { leftPercent, widthPercent } = barLayout(rowExtent(row), totalNs);
  const color = serviceColor(row.service);
  const indent = Math.min(row.depth, MAX_INDENT_LEVELS) * INDENT_PX;

  return (
    <li className={failed ? "wf-row wf-row-error" : "wf-row"} data-testid="waterfall-row">
      <button
        type="button"
        className="wf-grid wf-select"
        aria-pressed={selected}
        onClick={onSelect}
      >
        <span className="wf-name" style={{ paddingLeft: `${indent}px` }}>
          <span className="service-chip" style={{ backgroundColor: color }} aria-hidden="true" />
          <span className="span-service">{row.service}</span>{" "}
          <span className="span-name">{row.name}</span>
          {failed && <span className="error-label">error</span>}
        </span>
        <span className="wf-track" aria-hidden="true">
          <span
            className={failed ? "wf-bar wf-bar-error" : "wf-bar"}
            style={{
              left: `${leftPercent}%`,
              width: `${widthPercent}%`,
              backgroundColor: failed ? undefined : color,
            }}
          />
        </span>
      </button>
    </li>
  );
}

interface ScaleProps {
  readonly ticks: readonly ScaleTick[];
}

/** The time scale above the rows. The middle labels are hidden on narrow screens by CSS. */
function Scale({ ticks }: ScaleProps) {
  return (
    <span className="wf-scale">
      {ticks.map((tick, index) => {
        const isLast = index === ticks.length - 1;
        const position =
          index === 0 ? "wf-tick-start" : isLast ? "wf-tick-end" : "wf-tick-middle";
        return (
          <span
            key={index}
            className={`wf-tick ${position}`}
            style={{ left: `${tick.percent}%` }}
          >
            {formatDuration(tick.valueNs)}
          </span>
        );
      })}
    </span>
  );
}

interface SpanDetailsProps {
  readonly row: SpanRow;
}

/** The details of the selected span: where it ran, how it ended and its attributes. */
function SpanDetails({ row }: SpanDetailsProps) {
  const failed = row.statusCode === STATUS_ERROR;
  return (
    <aside className="span-details" data-testid="span-details" aria-labelledby="span-details-title">
      <h3 id="span-details-title">
        <span className="span-name">{row.name}</span>
      </h3>
      <dl className="details-list">
        <dt>Service</dt>
        <dd>
          <span
            className="service-chip"
            style={{ backgroundColor: serviceColor(row.service) }}
            aria-hidden="true"
          />
          {row.service}
        </dd>
        <dt>Duration</dt>
        <dd>{formatDuration(BigInt(row.durationNs))}</dd>
        <dt>Start offset</dt>
        <dd>{formatDuration(BigInt(row.offsetNs))}</dd>
        <dt>Status</dt>
        <dd className={failed ? "text-error" : undefined}>{statusLabel(row.statusCode)}</dd>
        {row.statusMessage !== "" && (
          <>
            <dt>Message</dt>
            <dd className={failed ? "text-error" : undefined}>{row.statusMessage}</dd>
          </>
        )}
        <dt>Span ID</dt>
        <dd className="mono">{row.spanId}</dd>
      </dl>

      <h4>Attributes</h4>
      {row.attributes.length === 0 ? (
        <p className="message">No attributes.</p>
      ) : (
        <dl className="details-list attributes">
          {row.attributes.map((attribute, index) => (
            <AttributeEntry key={index} attribute={attribute} />
          ))}
        </dl>
      )}
    </aside>
  );
}

function AttributeEntry({ attribute }: { readonly attribute: SpanAttribute }) {
  return (
    <>
      <dt className="mono">{attribute.key}</dt>
      <dd>{attributeText(attribute.value)}</dd>
    </>
  );
}

function rowExtent(row: SpanRow): Extent {
  return { offsetNs: BigInt(row.offsetNs), durationNs: BigInt(row.durationNs) };
}
