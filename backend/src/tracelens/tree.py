"""Assemble spans into a trace tree laid out in waterfall order.

The assembly is pure and iterative: it never recurses, so arbitrarily deep parent chains are
safe, and it never raises on malformed parent relations. Malformed input is repaired and
reported through the counters on :class:`TraceTree`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tracelens.model import Span

_SpanKey = tuple[str, str]
"""Identity of a span: ``(trace_id, span_id)``, the same key the store uses."""

_OrderKey = tuple[int, str, str]
"""Sort key ``(start_ns, span_id, trace_id)``; total over distinct spans."""


@dataclass(frozen=True, slots=True)
class Row:
    """One span placed in the waterfall.

    ``depth`` is ``0`` for a root. ``offset_ns`` is the span's start minus the earliest start
    among the spans of the same trace, so it is never negative.
    """

    span: Span
    depth: int
    offset_ns: int


@dataclass(frozen=True, slots=True)
class TraceTree:
    """Rows in depth-first waterfall order plus the repairs made while assembling them.

    ``orphans`` counts spans whose parent id is absent from the input. ``cycles_broken``
    counts parent cycles; each one is opened by treating its earliest-starting member as a root.
    """

    rows: list[Row]
    orphans: int
    cycles_broken: int


def build_tree(spans: Iterable[Span]) -> TraceTree:
    """Build the waterfall rows for ``spans``.

    Spans are identified by ``(trace_id, span_id)``. When an identity repeats, the first
    occurrence in ``spans`` is kept and later ones are ignored. A span whose parent is not in
    the input becomes a root and is counted as an orphan. A span with no parent is a root and is
    not counted. Each parent cycle is broken by detaching its earliest-starting member, which
    then becomes a root.

    Children, and roots, are ordered by ``(start_ns, span_id)``, with ``trace_id`` as a final
    tiebreaker. Offsets are relative to the earliest start among the kept spans of the same
    trace. The function never raises on well-formed :class:`Span` values.
    """
    by_key: dict[_SpanKey, Span] = {}
    for span in spans:
        by_key.setdefault((span.trace_id, span.span_id), span)

    parent_of: dict[_SpanKey, _SpanKey | None] = {}
    orphans = 0
    for key, span in by_key.items():
        if span.parent_span_id is None:
            parent_of[key] = None
            continue
        parent_key = (span.trace_id, span.parent_span_id)
        if parent_key in by_key:
            parent_of[key] = parent_key
        else:
            parent_of[key] = None
            orphans += 1

    cycles_broken = _break_cycles(by_key, parent_of)

    trace_start: dict[str, int] = {}
    for span in by_key.values():
        earliest = trace_start.get(span.trace_id)
        if earliest is None or span.start_ns < earliest:
            trace_start[span.trace_id] = span.start_ns

    children: dict[_SpanKey, list[_SpanKey]] = {}
    roots: list[_SpanKey] = []
    for key, parent in parent_of.items():
        if parent is None:
            roots.append(key)
        else:
            children.setdefault(parent, []).append(key)

    order = {key: _order_key(span) for key, span in by_key.items()}
    roots.sort(key=order.__getitem__)
    for siblings in children.values():
        siblings.sort(key=order.__getitem__)

    rows: list[Row] = []
    stack: list[tuple[_SpanKey, int]] = [(key, 0) for key in reversed(roots)]
    while stack:
        key, depth = stack.pop()
        span = by_key[key]
        rows.append(
            Row(
                span=span,
                depth=depth,
                offset_ns=span.start_ns - trace_start[span.trace_id],
            )
        )
        stack.extend((child, depth + 1) for child in reversed(children.get(key, ())))

    return TraceTree(rows=rows, orphans=orphans, cycles_broken=cycles_broken)


def _order_key(span: Span) -> _OrderKey:
    return (span.start_ns, span.span_id, span.trace_id)


def _break_cycles(by_key: dict[_SpanKey, Span], parent_of: dict[_SpanKey, _SpanKey | None]) -> int:
    """Detach one member of every parent cycle in place and return how many were found.

    Each span has at most one parent, so the parent relation is a functional graph and every
    cycle is simple. Walking up from each unsettled span either reaches a settled span or
    the root of the chain, or revisits a span on the current walk, which closes a cycle.
    """
    settled: set[_SpanKey] = set()
    cycles = 0
    for start in by_key:
        if start in settled:
            continue
        path: list[_SpanKey] = []
        on_path: set[_SpanKey] = set()
        node: _SpanKey | None = start
        while node is not None and node not in settled:
            if node in on_path:
                cycle = path[path.index(node) :]
                earliest = min(cycle, key=lambda key: _order_key(by_key[key]))
                parent_of[earliest] = None
                cycles += 1
                break
            on_path.add(node)
            path.append(node)
            node = parent_of[node]
        settled.update(path)
    return cycles
