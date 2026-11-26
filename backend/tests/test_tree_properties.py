"""Property-based invariants of trace tree assembly.

Random forests are generated with duplicate ids, orphans, self-parents and parent cycles, then
shuffled. Each property is checked against a reference computed from the input, not from the
implementation's internals. An exception raised by :func:`build_tree` fails the example.
"""

from __future__ import annotations

from typing import NamedTuple

from hypothesis import given, settings
from hypothesis import strategies as st

from tracelens.model import Span
from tracelens.tree import build_tree

TRACE = "0af7651916cd43dd8448eb211c80319c"
OTHER_TRACE = "1bf7651916cd43dd8448eb211c80319d"
TRACES = (TRACE, OTHER_TRACE)
MAX_SPANS = 24
MAX_START_NS = 50

_Key = tuple[str, str]
_PROPERTY_SETTINGS = settings(max_examples=200, deadline=None)


class _Case(NamedTuple):
    """A generated input with its shuffled variants.

    ``spans`` is the generated input, ``shuffled`` is a permutation of it (duplicates included),
    and ``distinct_shuffled`` is a permutation of its first occurrences only.
    """

    spans: list[Span]
    shuffled: list[Span]
    distinct_shuffled: list[Span]


def _hex_id(value: int) -> str:
    return f"{value:016x}"


def _make_span(trace_id: str, span_id: str, parent: str | None, start_ns: int) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service="api",
        name=f"op-{span_id}",
        kind=1,
        start_ns=start_ns,
        end_ns=start_ns + 10,
        status_code=0,
        status_message="",
        attributes=(),
    )


def _key(span: Span) -> _Key:
    return (span.trace_id, span.span_id)


def _parent_key(span: Span) -> _Key | None:
    if span.parent_span_id is None:
        return None
    return (span.trace_id, span.parent_span_id)


def _first_occurrences(spans: list[Span]) -> dict[_Key, Span]:
    kept: dict[_Key, Span] = {}
    for span in spans:
        kept.setdefault(_key(span), span)
    return kept


def _cycle_through(start: _Key, resolved: dict[_Key, _Key | None]) -> list[_Key] | None:
    """Return the members of the cycle that ``start`` lies on, or ``None`` if it lies on none."""
    members = [start]
    node = resolved[start]
    for _ in range(len(resolved)):
        if node is None:
            return None
        if node == start:
            return members
        members.append(node)
        node = resolved[node]
    return None


def _count_cycles(kept: dict[_Key, Span]) -> int:
    """Count parent cycles among ``kept``, each identified by its smallest member."""
    resolved: dict[_Key, _Key | None] = {}
    for key, span in kept.items():
        parent = _parent_key(span)
        resolved[key] = parent if parent is not None and parent in kept else None
    cycles = 0
    for start in kept:
        members = _cycle_through(start, resolved)
        if members is not None and min(members) == start:
            cycles += 1
    return cycles


@st.composite
def _random_spans(draw: st.DrawFn) -> list[Span]:
    """Spans with arbitrary ids, so duplicates, orphans, self-parents and cycles all occur."""
    count = draw(st.integers(0, MAX_SPANS))
    spans: list[Span] = []
    for _ in range(count):
        trace_id = draw(st.sampled_from(TRACES))
        span_id = _hex_id(draw(st.integers(0, count)))
        parent = draw(st.none() | st.integers(0, count + 2).map(_hex_id))
        start_ns = draw(st.integers(0, MAX_START_NS))
        spans.append(_make_span(trace_id, span_id, parent, start_ns))
    return spans


@st.composite
def _forest_spans(draw: st.DrawFn) -> list[Span]:
    """A single-trace forest with unique ids, where some parents are randomly rewired."""
    trace_id = draw(st.sampled_from(TRACES))
    count = draw(st.integers(0, MAX_SPANS))
    spans: list[Span] = []
    for index in range(count):
        parent: str | None = None
        if index > 0 and draw(st.booleans()):
            parent = _hex_id(draw(st.integers(0, index - 1)))
        if draw(st.integers(0, 4)) == 0:
            parent = draw(st.none() | st.integers(0, count + 2).map(_hex_id))
        start_ns = draw(st.integers(0, MAX_START_NS))
        spans.append(_make_span(trace_id, _hex_id(index), parent, start_ns))
    return spans


@st.composite
def _cases(draw: st.DrawFn) -> _Case:
    spans = draw(st.one_of(_random_spans(), _forest_spans()))
    distinct = list(_first_occurrences(spans).values())
    return _Case(
        spans=spans,
        shuffled=draw(st.permutations(spans)),
        distinct_shuffled=draw(st.permutations(distinct)),
    )


@_PROPERTY_SETTINGS
@given(_cases())
def test_each_kept_span_appears_exactly_once_and_first_occurrence_wins(case: _Case) -> None:
    kept = _first_occurrences(case.shuffled)

    tree = build_tree(case.shuffled)

    assert len(tree.rows) == len(kept)
    assert {_key(row.span): row.span for row in tree.rows} == kept


@_PROPERTY_SETTINGS
@given(_cases())
def test_parent_precedes_child_and_depth_is_parent_depth_plus_one(case: _Case) -> None:
    tree = build_tree(case.spans)
    position = {_key(row.span): index for index, row in enumerate(tree.rows)}

    for index, row in enumerate(tree.rows):
        if row.depth == 0:
            continue
        parent = _parent_key(row.span)
        assert parent is not None
        assert parent in position
        parent_index = position[parent]
        assert parent_index < index
        assert tree.rows[parent_index].depth == row.depth - 1


@_PROPERTY_SETTINGS
@given(_cases())
def test_roots_have_depth_zero_and_their_count_matches_the_input(case: _Case) -> None:
    kept = _first_occurrences(case.spans)
    tree = build_tree(case.spans)

    for row in tree.rows:
        parent = _parent_key(row.span)
        if parent is None or parent not in kept:
            assert row.depth == 0

    roots = sum(1 for row in tree.rows if row.depth == 0)
    parentless = sum(1 for span in kept.values() if span.parent_span_id is None)
    assert roots == parentless + tree.orphans + tree.cycles_broken


@_PROPERTY_SETTINGS
@given(_cases())
def test_orphans_and_cycles_broken_match_the_input(case: _Case) -> None:
    kept = _first_occurrences(case.spans)

    tree = build_tree(case.spans)

    expected_orphans = sum(
        1
        for span in kept.values()
        if _parent_key(span) is not None and _parent_key(span) not in kept
    )
    assert tree.orphans == expected_orphans
    assert tree.cycles_broken == _count_cycles(kept)


@_PROPERTY_SETTINGS
@given(_cases())
def test_output_is_independent_of_input_order(case: _Case) -> None:
    assert build_tree(case.spans) == build_tree(case.distinct_shuffled)


@_PROPERTY_SETTINGS
@given(_cases())
def test_offsets_are_non_negative_and_relative_to_trace_start(case: _Case) -> None:
    kept = _first_occurrences(case.shuffled)
    earliest: dict[str, int] = {}
    for span in kept.values():
        earliest[span.trace_id] = min(span.start_ns, earliest.get(span.trace_id, span.start_ns))

    tree = build_tree(case.shuffled)

    for row in tree.rows:
        assert row.offset_ns >= 0
        assert row.offset_ns == row.span.start_ns - earliest[row.span.trace_id]
