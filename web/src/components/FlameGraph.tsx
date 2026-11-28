import { useEffect, useMemo, useRef, useState } from "react";

import type { SpanRow } from "../api";
import { flameFrames } from "../flame";
import { formatDuration } from "../format";
import { frameBox, frameLabel } from "../flameview";
import { serviceColor } from "../waterfall";

/** Height of one row of frames, in pixels. */
const ROW_PX = 22;
/** Space left between stacked frames, in pixels. */
const GAP_PX = 1;
/** Space between a frame's left edge and its label, in pixels. */
const LABEL_INSET_PX = 4;
/** Narrowest drawing, in pixels; a narrower container scrolls sideways instead of squeezing. */
const MIN_WIDTH_PX = 600;

interface FlameGraphProps {
  /** The spans of one trace, in any order. */
  readonly spans: readonly SpanRow[];
}

/**
 * The flame graph of one trace: a box per span, stacked by depth in the span tree and placed by
 * its time range. Boxes take the colour of their service; error spans are drawn in the error
 * colour. Each box has a tooltip with its name, service and duration.
 *
 * The drawing is as wide as its container, but never narrower than {@link MIN_WIDTH_PX}, so the
 * labels keep their size on a phone and the container scrolls instead.
 */
export function FlameGraph({ spans }: FlameGraphProps) {
  const frames = useMemo(() => flameFrames(spans), [spans]);
  const rowsById = useMemo(
    () => new Map(spans.map((row) => [row.spanId, row] as const)),
    [spans],
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(MIN_WIDTH_PX);

  useEffect(() => {
    const element = containerRef.current;
    if (element === null) {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const [entry] = entries;
      if (entry !== undefined) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const width = Math.max(containerWidth, MIN_WIDTH_PX);
  const depth = frames.reduce((deepest, frame) => Math.max(deepest, frame.depth + 1), 0);
  const height = depth * ROW_PX;

  return (
    <div className="flame" ref={containerRef}>
      {frames.length === 0 ? (
        <p className="message">No spans.</p>
      ) : (
        <div className="flame-scroll">
          <svg
            className="flame-chart"
            role="group"
            aria-label="Flame graph of the spans"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
          >
            {frames.map((frame) => {
              const row = rowsById.get(frame.spanId);
              if (row === undefined) {
                return null;
              }
              const box = frameBox(frame, width);
              const top = frame.depth * ROW_PX;
              const label = frameLabel(frame.label, box.widthPx);
              return (
                <g key={frame.spanId}>
                  <title>
                    {`${frame.label} · ${frame.service} · ${formatDuration(BigInt(row.durationNs))}`}
                  </title>
                  <rect
                    className={frame.isError ? "flame-frame flame-frame-error" : "flame-frame"}
                    style={frame.isError ? undefined : { fill: serviceColor(frame.service) }}
                    x={box.xPx}
                    y={top + GAP_PX}
                    width={box.widthPx}
                    height={ROW_PX - 2 * GAP_PX}
                  />
                  {label !== "" && (
                    <text
                      className="flame-label"
                      x={box.xPx + LABEL_INSET_PX}
                      y={top + ROW_PX / 2}
                      dominantBaseline="central"
                    >
                      {label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}
