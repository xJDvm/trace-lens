"""Unit tests for trace tree assembly."""

from __future__ import annotations

from tracelens.model import Span
from tracelens.tree import TraceTree, build_tree

TRACE = "0af7651916cd43dd8448eb211c80319c"
OTHER_TRACE = "1bf7651916cd43dd8448eb211c80319d"


def _span(
    span_id: str,
    parent: str | None = None,
    start_ns: int = 100,
    *,
    trace_id: str = TRACE,
) -> Span:
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


def _layout(tree: TraceTree) -> list[tuple[str, int, int]]:
    return [(row.span.span_id, row.depth, row.offset_ns) for row in tree.rows]


def test_empty_input_gives_empty_tree() -> None:
    assert build_tree([]) == TraceTree(rows=[], orphans=0, cycles_broken=0)


def test_simple_tree_is_in_waterfall_order() -> None:
    spans = [
        _span("c", "a", start_ns=130),
        _span("a", None, start_ns=100),
        _span("b", "a", start_ns=110),
        _span("d", "b", start_ns=115),
    ]

    tree = build_tree(spans)

    assert _layout(tree) == [("a", 0, 0), ("b", 1, 10), ("d", 2, 15), ("c", 1, 30)]
    assert tree.orphans == 0
    assert tree.cycles_broken == 0


def test_children_with_equal_start_are_ordered_by_span_id() -> None:
    spans = [
        _span("root", None, start_ns=0),
        _span("z", "root", start_ns=5),
        _span("m", "root", start_ns=5),
    ]

    assert _layout(build_tree(spans)) == [("root", 0, 0), ("m", 1, 5), ("z", 1, 5)]


def test_output_does_not_depend_on_input_order() -> None:
    spans = [
        _span("a", None, start_ns=100),
        _span("b", "a", start_ns=110),
        _span("c", "a", start_ns=105),
        _span("e", None, start_ns=50),
    ]

    assert build_tree(spans) == build_tree(list(reversed(spans)))


def test_missing_parent_makes_root_and_counts_orphan() -> None:
    spans = [
        _span("a", None, start_ns=100),
        _span("x", "gone", start_ns=90),
        _span("y", "x", start_ns=95),
    ]

    tree = build_tree(spans)

    assert _layout(tree) == [("x", 0, 0), ("y", 1, 5), ("a", 0, 10)]
    assert tree.orphans == 1
    assert tree.cycles_broken == 0


def test_offsets_are_relative_to_earliest_start_of_each_trace() -> None:
    spans = [
        _span("a", None, start_ns=1_000),
        _span("b", None, start_ns=400, trace_id=OTHER_TRACE),
        _span("c", "a", start_ns=1_250),
    ]

    tree = build_tree(spans)

    offsets = {row.span.span_id: row.offset_ns for row in tree.rows}
    assert offsets == {"a": 0, "b": 0, "c": 250}


def test_duplicate_span_id_keeps_first_occurrence() -> None:
    first = _span("a", None, start_ns=100)
    second = Span(
        trace_id=TRACE,
        span_id="a",
        parent_span_id=None,
        service="other",
        name="duplicate",
        kind=1,
        start_ns=50,
        end_ns=60,
        status_code=0,
        status_message="",
        attributes=(),
    )
    child = _span("b", "a", start_ns=120)

    tree = build_tree([first, second, child])

    assert [row.span for row in tree.rows] == [first, child]
    assert _layout(tree) == [("a", 0, 0), ("b", 1, 20)]


def test_child_of_duplicate_attaches_to_kept_span() -> None:
    kept = _span("a", None, start_ns=100)
    dropped = _span("a", None, start_ns=999)
    child = _span("b", "a", start_ns=101)

    tree = build_tree([kept, dropped, child])

    assert _layout(tree) == [("a", 0, 0), ("b", 1, 1)]
    assert tree.orphans == 0


def test_same_span_id_in_different_traces_is_not_a_duplicate() -> None:
    spans = [
        _span("a", None, start_ns=100),
        _span("a", None, start_ns=200, trace_id=OTHER_TRACE),
    ]

    tree = build_tree(spans)

    assert len(tree.rows) == 2
    assert tree.orphans == 0


def test_two_span_cycle_is_broken_at_earliest_member() -> None:
    spans = [
        _span("a", "b", start_ns=100),
        _span("b", "a", start_ns=200),
    ]

    tree = build_tree(spans)

    assert _layout(tree) == [("a", 0, 0), ("b", 1, 100)]
    assert tree.cycles_broken == 1
    assert tree.orphans == 0


def test_three_span_cycle_is_broken_at_earliest_member() -> None:
    spans = [
        _span("a", "b", start_ns=300),
        _span("b", "c", start_ns=100),
        _span("c", "a", start_ns=200),
    ]

    tree = build_tree(spans)

    assert _layout(tree) == [("b", 0, 0), ("a", 1, 200), ("c", 2, 100)]
    assert tree.cycles_broken == 1
    assert tree.orphans == 0


def test_self_parent_is_a_cycle() -> None:
    tree = build_tree([_span("a", "a", start_ns=100)])

    assert _layout(tree) == [("a", 0, 0)]
    assert tree.cycles_broken == 1


def test_subtree_hanging_off_a_cycle_keeps_its_depth() -> None:
    spans = [
        _span("a", "b", start_ns=100),
        _span("b", "a", start_ns=200),
        _span("c", "b", start_ns=210),
    ]

    tree = build_tree(spans)

    assert _layout(tree) == [("a", 0, 0), ("b", 1, 100), ("c", 2, 110)]
    assert tree.cycles_broken == 1


def test_two_independent_cycles_are_both_counted() -> None:
    spans = [
        _span("a", "b", start_ns=1),
        _span("b", "a", start_ns=2),
        _span("c", "d", start_ns=3),
        _span("d", "c", start_ns=4),
    ]

    tree = build_tree(spans)

    assert tree.cycles_broken == 2
    assert [row.span.span_id for row in tree.rows] == ["a", "b", "c", "d"]


def test_deep_chain_does_not_hit_recursion_limit() -> None:
    depth = 10_000
    spans = [_span("s0", None, start_ns=0)]
    spans.extend(_span(f"s{i}", f"s{i - 1}", start_ns=i) for i in range(1, depth))

    tree = build_tree(spans)

    assert len(tree.rows) == depth
    assert tree.rows[-1].depth == depth - 1
    assert tree.rows[-1].span.span_id == f"s{depth - 1}"
    assert tree.orphans == 0
    assert tree.cycles_broken == 0
