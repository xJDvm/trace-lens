"""Exact latency percentiles and bucketed histograms over span durations.

Both functions are pure and never touch I/O. Percentiles use the nearest-rank method, so every
returned value is one of the input values. Durations are integers in nanoseconds.
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from fractions import Fraction


def percentiles(sorted_ns: Sequence[int], qs: Sequence[float]) -> list[int | None]:
    """Return the nearest-rank percentile of ``sorted_ns`` for each ``q`` in ``qs``.

    For a percentile ``q`` the rank is ``ceil(q / 100 * n)`` for ``n`` values, and the result
    is the value at the 1-based rank, clamped to the first and last value. ``q = 0`` therefore
    yields the minimum and ``q = 100`` the maximum. The arithmetic is exact (``Fraction``), so
    no float rounding can shift a rank.

    ``sorted_ns`` must already be sorted in ascending order; this is not checked. When it is
    empty, ``None`` is returned for every ``q``.

    Raises:
        ValueError: if any ``q`` is outside ``[0, 100]`` or is NaN.
    """
    for q in qs:
        if not 0 <= q <= 100:
            raise ValueError(f"percentile must be within [0, 100], got {q!r}")

    count = len(sorted_ns)
    if count == 0:
        return [None] * len(qs)

    result: list[int | None] = []
    for q in qs:
        rank = math.ceil(Fraction(q) * count / 100)
        index = min(max(rank - 1, 0), count - 1)
        result.append(sorted_ns[index])
    return result


def histogram(values_ns: Iterable[int], bucket_bounds: Sequence[int]) -> list[tuple[int, int, int]]:
    """Count ``values_ns`` into buckets delimited by ``bucket_bounds``.

    Given bounds ``b0 < b1 < ... < bk``, bucket ``j`` is the interval ``(b_j, b_j+1]`` and is
    reported as ``(b_j, b_j+1, count)``. Upper bounds are inclusive: a value equal to ``b_j+1``
    is counted in bucket ``j``, never in bucket ``j+1``. This matches the ``le`` convention of
    Prometheus-style histograms.

    The outer buckets are open towards the outside so that every value is counted exactly once
    and the counts sum to the number of values: values at or below ``b0`` fall into the first
    bucket, and values above ``bk`` fall into the last bucket. ``b0`` and ``bk`` are the
    explicit lower bound of the first bucket and upper bound of the last one.

    Returns one tuple per bucket, in bound order. Empty input gives every bucket a count of 0.

    Raises:
        ValueError: if fewer than two bounds are given or the bounds are not strictly increasing.
    """
    bounds = list(bucket_bounds)
    if len(bounds) < 2:
        raise ValueError("at least two bucket bounds are required")
    if any(lower >= upper for lower, upper in itertools.pairwise(bounds)):
        raise ValueError("bucket bounds must be strictly increasing")

    last_bucket = len(bounds) - 2
    counts = [0] * (len(bounds) - 1)
    for value in values_ns:
        index = min(max(bisect_left(bounds, value) - 1, 0), last_bucket)
        counts[index] += 1
    return [(bounds[j], bounds[j + 1], counts[j]) for j in range(len(counts))]


def default_bounds() -> list[int]:
    """Return log-spaced bucket bounds in nanoseconds, from 1 µs to 100 s.

    There are three bounds per decade, giving 25 strictly increasing integers that can be passed
    straight to :func:`histogram`.
    """
    return [round(10 ** (3 + step / 3)) for step in range(25)]
