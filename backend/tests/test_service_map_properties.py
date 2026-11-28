"""Property-based checks of the cross-service edge counts behind the service map.

Random multi-trace span trees are generated over a small service alphabet, with random status
codes and some orphan spans whose parent is absent. The store's edge counts are compared with a
reference computed in plain Python from the generated input.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from hypothesis import given, settings
from hypothesis import strategies as st

from tracelens.model import Span
from tracelens.store import Store

SERVICES = ("api", "db", "web")
STATUS_CODES = (0, 1, 2)
ERROR = 2
MISSING_PARENT = "f" * 16
MAX_TRACES = 4
MAX_SPANS_PER_TRACE = 12
_PROPERTY_SETTINGS = settings(max_examples=100, deadline=None)

_Edge = tuple[str, str]


def _make_span(
    trace_id: str, span_id: str, parent: str | None, service: str, status_code: int
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service=service,
        name=f"op-{span_id}",
        kind=2,
        start_ns=1_000,
        end_ns=1_100,
        status_code=status_code,
        status_message="",
        attributes=(),
    )


def _draw_parent(draw: st.DrawFn, earlier: list[str]) -> str | None:
    """Pick a parent that is an earlier span, absent (orphan), or none (a root)."""
    linked = draw(st.booleans())
    if earlier and linked:
        return draw(st.sampled_from(earlier))
    return draw(st.sampled_from((None, MISSING_PARENT)))


@st.composite
def _traces(draw: st.DrawFn) -> list[Span]:
    spans: list[Span] = []
    trace_count = draw(st.integers(min_value=1, max_value=MAX_TRACES))
    for trace_index in range(trace_count):
        trace_id = f"{trace_index + 1:032x}"
        count = draw(st.integers(min_value=0, max_value=MAX_SPANS_PER_TRACE))
        span_ids = [f"{index + 1:016x}" for index in range(count)]
        for index, span_id in enumerate(span_ids):
            parent = _draw_parent(draw, span_ids[:index])
            service = draw(st.sampled_from(SERVICES))
            status_code = draw(st.sampled_from(STATUS_CODES))
            spans.append(_make_span(trace_id, span_id, parent, service, status_code))
    return spans


def _reference_edges(spans: Iterable[Span]) -> dict[_Edge, tuple[int, int]]:
    """Return ``(calls, errors)`` per ``(caller, callee)`` pair, computed from the raw spans."""
    spans = list(spans)
    service_of = {(span.trace_id, span.span_id): span.service for span in spans}
    calls: Counter[_Edge] = Counter()
    errors: Counter[_Edge] = Counter()
    for span in spans:
        if span.parent_span_id is None:
            continue
        caller = service_of.get((span.trace_id, span.parent_span_id))
        if caller is None or caller == span.service:
            continue
        edge = (caller, span.service)
        calls[edge] += 1
        if span.status_code == ERROR:
            errors[edge] += 1
    return {edge: (calls[edge], errors[edge]) for edge in calls}


@_PROPERTY_SETTINGS
@given(spans=_traces())
def test_service_edge_calls_match_cross_service_child_count(spans: list[Span]) -> None:
    store = Store(":memory:")
    try:
        store.insert_spans(spans)
        edges = store.service_edges(None, MAX_TRACES)
    finally:
        store.close()
    reference = _reference_edges(spans)
    assert sum(edge.calls for edge in edges) == sum(calls for calls, _ in reference.values())
    assert {(edge.caller, edge.callee): (edge.calls, edge.errors) for edge in edges} == reference


@_PROPERTY_SETTINGS
@given(spans=_traces())
def test_service_edge_errors_never_exceed_calls(spans: list[Span]) -> None:
    store = Store(":memory:")
    try:
        store.insert_spans(spans)
        edges = store.service_edges(None, MAX_TRACES)
    finally:
        store.close()
    assert all(0 <= edge.errors <= edge.calls for edge in edges)
