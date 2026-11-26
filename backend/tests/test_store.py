"""Tests for the SQLite span and trace store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tracelens.model import AttrValue, Span
from tracelens.store import Store, TraceSummary

TRACE = "0af7651916cd43dd8448eb211c80319c"
OTHER_TRACE = "1bf7651916cd43dd8448eb211c80319d"
ERROR = 2
OK = 1


def _span(
    span_id: str,
    *,
    trace_id: str = TRACE,
    parent: str | None = None,
    service: str = "api",
    name: str | None = None,
    start_ns: int = 1_000,
    duration_ns: int = 100,
    status_code: int = 0,
    attributes: tuple[tuple[str, AttrValue], ...] = (),
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service=service,
        name=name if name is not None else f"op-{span_id}",
        kind=2,
        start_ns=start_ns,
        end_ns=start_ns + duration_ns,
        status_code=status_code,
        status_message="",
        attributes=attributes,
    )


@pytest.fixture
def store() -> Iterator[Store]:
    db = Store(":memory:")
    yield db
    db.close()


def _list_all(store: Store, limit: int = 1_000) -> list[TraceSummary]:
    return store.list_traces(None, None, None, None, limit)


def _paginate(store: Store, limit: int, service: str | None = None) -> list[TraceSummary]:
    pages: list[TraceSummary] = []
    before: int | None = None
    before_trace_id: str | None = None
    while True:
        page = store.list_traces(service, None, None, None, limit, before, before_trace_id)
        pages.extend(page)
        if len(page) < limit:
            return pages
        before, before_trace_id = page[-1].start_ns, page[-1].trace_id


def test_insert_counts_new_spans_and_ignores_reingest(store: Store) -> None:
    batch = [_span("a"), _span("b", parent="a", start_ns=1_010)]
    assert store.insert_spans(batch) == 2
    assert store.insert_spans(batch) == 0
    assert store.insert_spans([]) == 0
    summary = _list_all(store)
    assert summary == [
        TraceSummary(
            trace_id=TRACE,
            start_ns=1_000,
            end_ns=1_110,
            span_count=2,
            error_count=0,
            root_service="api",
            root_name="op-a",
        )
    ]
    trace = store.get_trace(TRACE)
    assert trace is not None
    assert [span.span_id for span in trace[1]] == ["a", "b"]


def test_reingest_keeps_first_stored_span(store: Store) -> None:
    store.insert_spans([_span("a", name="first")])
    store.insert_spans([_span("a", name="second", status_code=ERROR)])
    trace = store.get_trace(TRACE)
    assert trace is not None
    summary, spans = trace
    assert [span.name for span in spans] == ["first"]
    assert summary.error_count == 0


def test_summary_spans_min_start_max_end_across_batches(store: Store) -> None:
    store.insert_spans([_span("late", start_ns=5_000, duration_ns=50)])
    store.insert_spans([_span("early", start_ns=1_000, duration_ns=10)])
    store.insert_spans([_span("long", start_ns=2_000, duration_ns=9_000)])
    (summary,) = _list_all(store)
    assert summary.start_ns == 1_000
    assert summary.end_ns == 11_000
    assert summary.duration_ns == 10_000
    assert summary.span_count == 3


def test_error_count_only_counts_status_error(store: Store) -> None:
    store.insert_spans(
        [
            _span("a", status_code=0),
            _span("b", parent="a", status_code=OK),
            _span("c", parent="a", status_code=ERROR),
            _span("d", parent="a", status_code=ERROR),
        ]
    )
    (summary,) = _list_all(store)
    assert summary.error_count == 2
    assert summary.span_count == 4


def test_root_is_parentless_span_with_earliest_start(store: Store) -> None:
    # A child can start before the root; the root is still the parentless span.
    store.insert_spans(
        [
            _span("child", parent="root", service="db", name="query", start_ns=900),
            _span("root", service="web", name="GET /", start_ns=1_000),
        ]
    )
    (summary,) = _list_all(store)
    assert (summary.root_service, summary.root_name) == ("web", "GET /")


def test_root_is_earliest_of_several_parentless_spans(store: Store) -> None:
    store.insert_spans(
        [
            _span("second", service="b", name="later", start_ns=2_000),
            _span("first", service="a", name="earliest", start_ns=1_500),
        ]
    )
    (summary,) = _list_all(store)
    assert (summary.root_service, summary.root_name) == ("a", "earliest")


def test_root_falls_back_to_earliest_span_without_parentless_span(store: Store) -> None:
    store.insert_spans(
        [
            _span("x", parent="p", service="late", name="late", start_ns=3_000),
            _span("y", parent="q", service="early", name="early", start_ns=2_000),
        ]
    )
    (summary,) = _list_all(store)
    assert (summary.root_service, summary.root_name) == ("early", "early")


def test_root_is_recomputed_when_root_arrives_later(store: Store) -> None:
    store.insert_spans([_span("child", parent="root", service="db", name="q", start_ns=1_100)])
    (before,) = _list_all(store)
    assert (before.root_service, before.root_name) == ("db", "q")
    store.insert_spans([_span("root", service="web", name="GET /", start_ns=1_000)])
    (after,) = _list_all(store)
    assert (after.root_service, after.root_name) == ("web", "GET /")


def test_summaries_are_refreshed_only_for_touched_traces(store: Store) -> None:
    store.insert_spans([_span("a"), _span("b", trace_id=OTHER_TRACE, start_ns=50)])
    store.insert_spans([_span("c", trace_id=TRACE, status_code=ERROR, start_ns=1_200)])
    by_id = {summary.trace_id: summary for summary in _list_all(store)}
    assert by_id[TRACE].span_count == 2
    assert by_id[TRACE].error_count == 1
    assert by_id[OTHER_TRACE].span_count == 1


def test_get_trace_returns_spans_with_attributes(store: Store) -> None:
    attributes = (
        ("service.name", "api"),
        ("http.status_code", 503),
        ("ratio", 0.25),
        ("cache.hit", False),
        ("note", 'héllo "quoted"'),
    )
    store.insert_spans([_span("a", attributes=attributes)])
    trace = store.get_trace(TRACE)
    assert trace is not None
    (span,) = trace[1]
    assert span.attributes == attributes
    assert span.duration_ns == 100
    assert span.parent_span_id is None
    assert span.kind == 2


def test_get_trace_unknown_id_is_none(store: Store) -> None:
    store.insert_spans([_span("a")])
    assert store.get_trace(OTHER_TRACE) is None


def test_services_are_distinct_and_sorted(store: Store) -> None:
    assert store.services() == []
    store.insert_spans(
        [
            _span("a", service="web"),
            _span("b", parent="a", service="auth"),
            _span("c", parent="a", service="web"),
        ]
    )
    assert store.services() == ["auth", "web"]


def test_filter_by_service(store: Store) -> None:
    store.insert_spans([_span("a", service="web")])
    store.insert_spans([_span("b", trace_id=OTHER_TRACE, service="api")])
    store.insert_spans([_span("c", trace_id=OTHER_TRACE, parent="b", service="db")])
    matched = store.list_traces("db", None, None, None, 10)
    assert [summary.trace_id for summary in matched] == [OTHER_TRACE]
    assert store.list_traces("missing", None, None, None, 10) == []


def test_filter_by_duration_bounds_are_inclusive(store: Store) -> None:
    store.insert_spans([_span("a", trace_id=TRACE, duration_ns=100)])
    store.insert_spans([_span("b", trace_id=OTHER_TRACE, duration_ns=200)])
    third = "2af7651916cd43dd8448eb211c80319e"
    store.insert_spans([_span("c", trace_id=third, duration_ns=300)])

    def ids(min_ns: int | None, max_ns: int | None) -> set[str]:
        return {s.trace_id for s in store.list_traces(None, min_ns, max_ns, None, 10)}

    assert ids(100, 300) == {TRACE, OTHER_TRACE, third}
    assert ids(101, None) == {OTHER_TRACE, third}
    assert ids(None, 199) == {TRACE}
    assert ids(200, 200) == {OTHER_TRACE}
    assert ids(201, 299) == set()


def test_filter_by_error(store: Store) -> None:
    store.insert_spans([_span("a", trace_id=TRACE)])
    store.insert_spans([_span("b", trace_id=OTHER_TRACE, status_code=ERROR)])
    assert [s.trace_id for s in store.list_traces(None, None, None, True, 10)] == [OTHER_TRACE]
    assert [s.trace_id for s in store.list_traces(None, None, None, False, 10)] == [TRACE]
    assert len(store.list_traces(None, None, None, None, 10)) == 2


def test_filters_combine(store: Store) -> None:
    store.insert_spans([_span("a", trace_id=TRACE, service="web", status_code=ERROR)])
    store.insert_spans([_span("b", trace_id=OTHER_TRACE, service="web", duration_ns=5_000)])
    store.insert_spans([_span("c", trace_id=OTHER_TRACE, parent="b", service="db")])
    result = store.list_traces("web", 1_000, None, True, 10)
    assert result == []
    result = store.list_traces("web", 1_000, None, False, 10)
    assert [s.trace_id for s in result] == [OTHER_TRACE]


def test_list_is_newest_first_and_respects_limit(store: Store) -> None:
    for index in range(5):
        store.insert_spans([_span(f"s{index}", trace_id=f"{index:032x}", start_ns=index * 10)])
    listed = store.list_traces(None, None, None, None, 3)
    assert [s.start_ns for s in listed] == [40, 30, 20]


def test_before_alone_returns_strictly_earlier_traces(store: Store) -> None:
    for index in range(3):
        store.insert_spans(
            [_span(f"s{index}", trace_id=f"{index:032x}", start_ns=(index + 1) * 10)]
        )
    listed = store.list_traces(None, None, None, None, 10, 30)
    assert [s.start_ns for s in listed] == [20, 10]


def test_cursor_pages_have_no_duplicates_or_gaps_with_equal_starts(store: Store) -> None:
    for index in range(25):
        trace_id = f"{index:032x}"
        store.insert_spans([_span("root", trace_id=trace_id, start_ns=100 * (index % 4))])
    everything = _list_all(store)
    assert len(everything) == 25
    for limit in (1, 2, 3, 7, 25, 100):
        paged = _paginate(store, limit)
        assert [s.trace_id for s in paged] == [s.trace_id for s in everything]


def test_cursor_respects_filters(store: Store) -> None:
    for index in range(10):
        service = "web" if index % 2 == 0 else "api"
        store.insert_spans(
            [_span("r", trace_id=f"{index:032x}", service=service, start_ns=10 * (index % 3))]
        )
    expected = store.list_traces("web", None, None, None, 100)
    assert len(expected) == 5
    assert [s.trace_id for s in _paginate(store, 2, "web")] == [s.trace_id for s in expected]


def test_cursor_argument_validation(store: Store) -> None:
    with pytest.raises(ValueError):
        store.list_traces(None, None, None, None, 0)
    with pytest.raises(ValueError):
        store.list_traces(None, None, None, None, 10, None, TRACE)


def test_latency_samples_returns_last_durations(store: Store) -> None:
    for index in range(5):
        store.insert_spans(
            [
                _span(
                    f"s{index}",
                    trace_id=f"{index:032x}",
                    name="GET /items",
                    start_ns=index * 10,
                    duration_ns=(index + 1) * 100,
                )
            ]
        )
    assert store.latency_samples(None, None, 2) == [500, 400]
    assert store.latency_samples(None, None, 100) == [500, 400, 300, 200, 100]


def test_latency_samples_filters_by_service_and_name(store: Store) -> None:
    store.insert_spans(
        [
            _span("a", service="web", name="GET /", duration_ns=10, start_ns=1),
            _span("b", service="web", name="POST /", duration_ns=20, start_ns=2),
            _span("c", service="db", name="GET /", duration_ns=30, start_ns=3),
        ]
    )
    assert store.latency_samples("web", None, 10) == [20, 10]
    assert store.latency_samples(None, "GET /", 10) == [30, 10]
    assert store.latency_samples("web", "GET /", 10) == [10]
    assert store.latency_samples("missing", None, 10) == []


def test_latency_samples_rejects_non_positive_limit(store: Store) -> None:
    with pytest.raises(ValueError):
        store.latency_samples(None, None, 0)


def test_failed_batch_is_rolled_back(store: Store) -> None:
    store.insert_spans([_span("a")])
    poisoned = _span("b", start_ns=2**70, duration_ns=0)
    with pytest.raises(OverflowError):
        store.insert_spans([_span("c", trace_id=OTHER_TRACE), poisoned])
    assert store.get_trace(OTHER_TRACE) is None
    trace = store.get_trace(TRACE)
    assert trace is not None
    assert [span.span_id for span in trace[1]] == ["a"]
    assert [s.trace_id for s in _list_all(store)] == [TRACE]


def test_data_survives_reopen_in_wal_mode(tmp_path: Path) -> None:
    path = tmp_path / "trace-lens.db"
    first = Store(path)
    first.insert_spans([_span("a", attributes=(("k", "v"),))])
    first.close()
    second = Store(path)
    try:
        trace = second.get_trace(TRACE)
        assert trace is not None
        assert trace[1][0].attributes == (("k", "v"),)
        journal = sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()
        assert journal == ("wal",)
    finally:
        second.close()


def test_schema_has_expected_indexes(tmp_path: Path) -> None:
    path = tmp_path / "trace-lens.db"
    Store(path).close()
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    finally:
        connection.close()
    names = {row[0] for row in rows}
    assert {"spans_service_start", "spans_service_name_duration", "traces_start"} <= names


@settings(max_examples=60, deadline=None)
@given(
    starts=st.lists(st.integers(min_value=0, max_value=5), min_size=0, max_size=30),
    limit=st.integers(min_value=1, max_value=6),
)
def test_cursor_pagination_matches_full_listing(starts: list[int], limit: int) -> None:
    db = Store(":memory:")
    try:
        for index, start in enumerate(starts):
            db.insert_spans([_span("r", trace_id=f"{index:032x}", start_ns=start)])
        expected = _list_all(db)
        assert [s.start_ns for s in expected] == sorted(
            (s.start_ns for s in expected), reverse=True
        )
        assert [s.trace_id for s in _paginate(db, limit)] == [s.trace_id for s in expected]
    finally:
        db.close()
