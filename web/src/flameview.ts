/**
 * Pixel helpers of the flame graph: where a frame is drawn and which part of its label fits.
 *
 * The flame graph is drawn at a width in pixels, so frame positions and label lengths are plain
 * numbers in pixels here. No React in this module.
 */

import type { Frame } from "./flame";
import { truncateLabel } from "./servicemapview";

/** Frames narrower than this, in pixels, show no label; the tooltip still names them. */
export const MIN_LABEL_PX = 40;

/** Narrowest frame drawn, in pixels, so that a span of no duration stays visible. */
export const MIN_FRAME_PX = 1;

/** Approximate advance of one label character, in pixels, at the flame graph's font size. */
const CHAR_PX = 7;

/** Space kept free on both sides of a label, in pixels. */
const LABEL_PADDING_PX = 8;

/** The horizontal box of a frame, in pixels. */
export interface FrameBox {
  readonly xPx: number;
  readonly widthPx: number;
}

/**
 * The box of a frame in a flame graph drawn `widthPx` pixels wide.
 *
 * @param frame - The frame, with its fractions of the trace width.
 * @param widthPx - The drawing width in pixels.
 * @returns The left edge and the width, the width being at least {@link MIN_FRAME_PX}.
 */
export function frameBox(frame: Pick<Frame, "x0" | "x1">, widthPx: number): FrameBox {
  return {
    xPx: frame.x0 * widthPx,
    widthPx: Math.max((frame.x1 - frame.x0) * widthPx, MIN_FRAME_PX),
  };
}

/**
 * The part of a span name that fits in a frame of `widthPx` pixels.
 *
 * A frame narrower than {@link MIN_LABEL_PX} gets an empty label. A wider frame gets the name
 * truncated, with an ellipsis, to the number of characters that fit.
 *
 * @param label - The span name.
 * @param widthPx - The width of the frame in pixels. A value that is not a number gets no label.
 * @returns The text to draw; may be empty.
 */
export function frameLabel(label: string, widthPx: number): string {
  if (!(widthPx >= MIN_LABEL_PX)) {
    return "";
  }
  const maxChars = Math.floor((widthPx - LABEL_PADDING_PX) / CHAR_PX);
  return truncateLabel(label, maxChars);
}
