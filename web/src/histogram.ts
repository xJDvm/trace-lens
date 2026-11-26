/**
 * Pure scale for the latency histogram: bar heights relative to the fullest bucket, and the upper
 * edge and label of every bucket.
 *
 * The API sends only the upper bound of each bucket, so a bucket is labelled by its upper edge
 * (`≤ 12.3 ms`). Bounds are `bigint` nanoseconds, as the API sends them.
 */

import type { LatencyBucket } from "./api";
import { formatDuration } from "./format";

/** One bar of the histogram. */
export interface HistogramBar {
  readonly count: number;
  /** Height in percent of the fullest bucket, in `[0, 100]`. */
  readonly heightPercent: number;
  /** Upper edge of the bucket (inclusive), in nanoseconds. */
  readonly upperNs: bigint;
  /** Axis label of the upper edge, e.g. `≤ 12.3 ms`. */
  readonly label: string;
}

/** The scale of a whole histogram: its bars in bucket order and the largest count. */
export interface HistogramScale {
  readonly maxCount: number;
  readonly bars: readonly HistogramBar[];
}

/**
 * Scales the buckets of a latency histogram for drawing.
 *
 * @param buckets - Buckets in ascending order of `leNs`, as returned by `GET /api/stats/latency`.
 * @returns One bar per bucket. When every count is zero, every bar has a height of 0.
 */
export function histogramScale(buckets: readonly LatencyBucket[]): HistogramScale {
  const maxCount = buckets.reduce((max, bucket) => Math.max(max, bucket.count), 0);
  const bars = buckets.map((bucket): HistogramBar => {
    const upperNs = BigInt(bucket.leNs);
    return {
      count: bucket.count,
      heightPercent: maxCount === 0 ? 0 : (bucket.count * 100) / maxCount,
      upperNs,
      label: `≤ ${formatDuration(upperNs)}`,
    };
  });
  return { maxCount, bars };
}
