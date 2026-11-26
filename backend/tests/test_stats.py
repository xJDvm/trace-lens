"""Unit and property tests for nearest-rank percentiles and latency histograms."""

from __future__ import annotations

import itertools
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tracelens.stats import default_bounds, histogram, percentiles

DURATIONS = st.lists(st.integers(min_value=0, max_value=10**12), max_size=200)
QUANTILES = st.floats(min_value=0, max_value=100, allow_nan=False)


def _reference_percentile(sorted_ns: list[int], q: float) -> int:
    """Smallest value whose cumulative share of the sample reaches ``q`` percent.

    Deliberately a linear scan over exact fractions, not the rank formula used in the module.
    """
    total = len(sorted_ns)
    for position, value in enumerate(sorted_ns, start=1):
        if position * 100 >= Fraction(q) * total:
            return value
    raise AssertionError("q within [0, 100] always reaches the last value")


def _reference_bucket(value: int, bounds: list[int]) -> int:
    """Index of the bucket ``(b_j, b_j+1]`` holding ``value``, with the outer buckets open."""
    for index in range(len(bounds) - 2):
        if value <= bounds[index + 1]:
            return index
    return len(bounds) - 2


@given(DURATIONS, st.lists(QUANTILES, max_size=10))
def test_percentiles_match_naive_reference(values: list[int], qs: list[float]) -> None:
    sorted_ns = sorted(values)

    result = percentiles(sorted_ns, qs)

    if not sorted_ns:
        assert result == [None] * len(qs)
    else:
        assert result == [_reference_percentile(sorted_ns, q) for q in qs]


@given(DURATIONS, st.lists(QUANTILES, min_size=1, max_size=10))
def test_percentiles_are_members_and_monotonic(values: list[int], qs: list[float]) -> None:
    sorted_ns = sorted(values)
    qs = sorted(qs)

    result = percentiles(sorted_ns, qs)

    if sorted_ns:
        values = [value for value in result if value is not None]
        assert set(values) <= set(sorted_ns)
        assert values == sorted(values)
    else:
        assert result == [None] * len(qs)


def test_empty_input_returns_none_per_quantile() -> None:
    assert percentiles([], [50, 95, 99]) == [None, None, None]
    assert percentiles([], []) == []


def test_single_value_is_every_percentile() -> None:
    assert percentiles([42], [0, 1, 50, 99, 100]) == [42, 42, 42, 42, 42]


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        ([10, 20, 30, 40], 25, 10),  # rank ceil(1) = 1
        ([10, 20, 30, 40], 50, 20),  # rank ceil(2) = 2
        ([10, 20, 30, 40], 50.5, 30),  # rank ceil(2.02) = 3
        ([10, 20, 30, 40], 75, 30),  # rank ceil(3) = 3
        ([10, 20, 30, 40], 100, 40),
        ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95, 10),  # rank ceil(9.5) = 10
        ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90, 9),  # rank exactly 9
    ],
)
def test_nearest_rank_examples(values: list[int], q: float, expected: int) -> None:
    assert percentiles(values, [q]) == [expected]


def test_q_zero_is_minimum_and_q_hundred_is_maximum() -> None:
    values = [7, 3, 9, 3, 12]
    sorted_ns = sorted(values)

    assert percentiles(sorted_ns, [0, 100]) == [3, 12]


@pytest.mark.parametrize("q", [-0.001, -1, 100.001, 101, float("nan"), float("inf")])
def test_percentiles_reject_out_of_range_quantiles(q: float) -> None:
    with pytest.raises(ValueError):
        percentiles([1, 2, 3], [50, q])


def test_percentiles_reject_out_of_range_quantile_even_when_empty() -> None:
    with pytest.raises(ValueError):
        percentiles([], [101])


def test_default_bounds_are_strictly_increasing_integers_from_1us_to_100s() -> None:
    bounds = default_bounds()

    assert bounds[0] == 1_000
    assert bounds[-1] == 100_000_000_000
    assert all(isinstance(bound, int) for bound in bounds)
    assert all(lower < upper for lower, upper in itertools.pairwise(bounds))
    assert len(bounds) == 25


@given(DURATIONS)
def test_histogram_counts_each_value_exactly_once(values: list[int]) -> None:
    buckets = histogram(values, default_bounds())

    assert sum(count for _, _, count in buckets) == len(values)


@given(DURATIONS)
def test_histogram_matches_per_value_reference(values: list[int]) -> None:
    bounds = [1, 10, 100, 1_000, 10_000]
    expected = [0] * (len(bounds) - 1)
    for value in values:
        expected[_reference_bucket(value, bounds)] += 1

    buckets = histogram(values, bounds)

    assert buckets == [(bounds[j], bounds[j + 1], expected[j]) for j in range(len(bounds) - 1)]


def test_histogram_upper_bound_belongs_to_its_own_bucket() -> None:
    # Upper bounds are inclusive: 10 is in (1, 10], not in (10, 100].
    buckets = histogram([10, 11, 100], [1, 10, 100])

    assert buckets == [(1, 10, 1), (10, 100, 2)]


def test_histogram_lower_bound_is_clamped_into_first_bucket() -> None:
    buckets = histogram([-5, 0, 1], [1, 10, 100])

    assert buckets == [(1, 10, 3), (10, 100, 0)]


def test_histogram_upper_overflow_is_clamped_into_last_bucket() -> None:
    buckets = histogram([101, 10**9], [1, 10, 100])

    assert buckets == [(1, 10, 0), (10, 100, 2)]


def test_histogram_empty_input_gives_zero_counts() -> None:
    assert histogram([], [1, 10, 100]) == [(1, 10, 0), (10, 100, 0)]


def test_histogram_accepts_any_iterable() -> None:
    assert histogram(iter([5, 50]), [1, 10, 100]) == [(1, 10, 1), (10, 100, 1)]


@pytest.mark.parametrize("bounds", [[], [10], [1, 1, 2], [5, 3], [1, 10, 10, 100]])
def test_histogram_rejects_invalid_bounds(bounds: list[int]) -> None:
    with pytest.raises(ValueError):
        histogram([1, 2, 3], bounds)
