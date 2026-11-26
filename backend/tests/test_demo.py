"""Tests for the seeded demo trace generator."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tracelens import demo
from tracelens.config import MAX_BODY_BYTES, MAX_SPANS_PER_REQUEST
from tracelens.model import Span
from tracelens.otlp import ParseResult, parse_export_request
from tracelens.store import Store
from tracelens.tree import build_tree

EXPECTED_SERVICES = frozenset(
    {
        "web-frontend",
        "api-gateway",
        "auth",
        "catalog",
        "postgres",
        "redis",
        "checkout",
        "payments",
    }
)
EXPECTED_EDGES = frozenset(
    {
        ("web-frontend", "api-gateway"),
        ("api-gateway", "auth"),
        ("api-gateway", "catalog"),
        ("api-gateway", "checkout"),
        ("auth", "postgres"),
        ("catalog", "redis"),
        ("catalog", "postgres"),
        ("checkout", "payments"),
    }
)
ANCHOR = demo.DEFAULT_ANCHOR_NS


def _parsed_spans(traces: list[list[Span]]) -> list[Span]:
    """Encode ``traces`` as request bodies and parse them back, asserting nothing is rejected."""
    spans: list[Span] = []
    for body in demo.export_requests(traces):
        result = parse_export_request(body)
        assert isinstance(result, ParseResult)
        assert result.rejected == 0, result.errors
        spans.extend(result.spans)
    return spans


def _by_trace(spans: Iterable[Span]) -> dict[str, list[Span]]:
    grouped: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        grouped[span.trace_id].append(span)
    return grouped


def test_same_seed_gives_identical_payload_bytes() -> None:
    first = demo.export_requests(demo.generate_traces(120, 7, ANCHOR))
    second = demo.export_requests(demo.generate_traces(120, 7, ANCHOR))
    assert first == second


def test_different_seeds_give_different_payloads() -> None:
    assert demo.export_requests(demo.generate_traces(20, 1, ANCHOR)) != demo.export_requests(
        demo.generate_traces(20, 2, ANCHOR)
    )


def test_payloads_parse_without_rejections_and_within_limits() -> None:
    traces = demo.generate_traces(250, 11, ANCHOR)
    bodies = demo.export_requests(traces)
    assert len(bodies) == 3
    for body in bodies:
        assert len(body) <= MAX_BODY_BYTES
        result = parse_export_request(body)
        assert isinstance(result, ParseResult)
        assert result.rejected == 0
        assert len(result.spans) <= MAX_SPANS_PER_REQUEST
    assert len(_parsed_spans(traces)) == sum(len(trace) for trace in traces)


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1), traces=st.integers(1, 15))
def test_any_seed_produces_valid_otlp(seed: int, traces: int) -> None:
    generated = demo.generate_traces(traces, seed, ANCHOR)
    spans = _parsed_spans(generated)
    assert len(spans) == sum(len(trace) for trace in generated)


def test_each_trace_tree_is_well_formed() -> None:
    spans = _parsed_spans(demo.generate_traces(200, 42, ANCHOR))
    for trace_spans in _by_trace(spans).values():
        tree = build_tree(trace_spans)
        assert tree.orphans == 0
        assert tree.cycles_broken == 0
        assert len(tree.rows) == len(trace_spans)
        roots = [row.span for row in tree.rows if row.depth == 0]
        assert [span.service for span in roots] == ["web-frontend"]
        services = {row.span.service for row in tree.rows}
        assert {"web-frontend", "api-gateway", "auth"} <= services
        assert services <= EXPECTED_SERVICES


def test_topology_covers_expected_services_and_edges() -> None:
    spans = _parsed_spans(demo.generate_traces(300, 42, ANCHOR))
    services = {span.service for span in spans}
    assert services == EXPECTED_SERVICES
    edges: set[tuple[str, str]] = set()
    for trace_spans in _by_trace(spans).values():
        by_id = {span.span_id: span for span in trace_spans}
        for span in trace_spans:
            if span.parent_span_id is not None:
                parent = by_id[span.parent_span_id]
                edges.add((parent.service, span.service))
    assert edges == EXPECTED_EDGES


def test_errors_are_reported_and_propagate_to_callers() -> None:
    spans = _parsed_spans(demo.generate_traces(1000, 42, ANCHOR))
    errors = [span for span in spans if span.status_code == 2]
    assert errors
    assert all(span.status_message for span in errors)
    assert {span.service for span in errors} >= {"payments", "checkout", "web-frontend"}
    for trace_spans in _by_trace(spans).values():
        by_id = {span.span_id: span for span in trace_spans}
        for span in trace_spans:
            parent = by_id.get(span.parent_span_id or "")
            if span.status_code == 2 and parent is not None:
                assert parent.status_code == 2


def test_children_are_nested_inside_their_parent() -> None:
    spans = _parsed_spans(demo.generate_traces(200, 5, ANCHOR))
    for trace_spans in _by_trace(spans).values():
        by_id = {span.span_id: span for span in trace_spans}
        for span in trace_spans:
            assert span.start_ns >= ANCHOR
            assert span.end_ns >= span.start_ns
            if span.parent_span_id is not None:
                parent = by_id[span.parent_span_id]
                assert parent.start_ns <= span.start_ns
                assert span.end_ns <= parent.end_ns


def test_db_output_is_readable_by_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "demo.db"
    assert demo.main(["--db", str(db_path), "--traces", "200", "--seed", "3"]) == 0
    span_total = sum(len(trace) for trace in demo.generate_traces(200, 3, ANCHOR))
    assert f"stored {span_total} new spans from 200 traces" in capsys.readouterr().out
    store = Store(db_path)
    try:
        summaries = store.list_traces(None, None, None, None, limit=500)
        assert len(summaries) == 200
        assert {summary.root_service for summary in summaries} == {"web-frontend"}
        assert set(store.services()) == EXPECTED_SERVICES
        assert store.get_trace(summaries[0].trace_id) is not None
    finally:
        store.close()


def test_db_rerun_with_same_seed_stores_nothing_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "demo.db"
    args = ["--db", str(db_path), "--traces", "10", "--seed", "9"]
    assert demo.main(args) == 0
    capsys.readouterr()
    assert demo.main(args) == 0
    assert "stored 0 new spans from 10 traces" in capsys.readouterr().out


def test_now_anchors_newest_trace_to_current_time(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    before = time.time_ns()
    assert demo.main(["--db", str(db_path), "--traces", "5", "--now"]) == 0
    store = Store(db_path)
    try:
        newest = store.list_traces(None, None, None, None, limit=1)[0]
    finally:
        store.close()
    assert before - 60 * 10**9 <= newest.start_ns <= time.time_ns() + 60 * 10**9


def test_anchor_must_be_positive() -> None:
    with pytest.raises(ValueError):
        demo.generate_traces(1, 0, 0)


class _Recorder:
    """Stands in for ``urllib.request.urlopen`` and records the requests it is given."""

    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> nullcontext[BytesIO]:
        assert timeout == demo.REQUEST_TIMEOUT_S
        self.requests.append(request)
        return nullcontext(BytesIO(b"{}"))


def test_url_posts_each_batch_to_ingestion_endpoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    assert demo.main(["--url", "http://collector.test:4318/", "--traces", "250"]) == 0
    assert len(recorder.requests) == 3
    for request in recorder.requests:
        assert request.full_url == "http://collector.test:4318/v1/traces"
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
    expected = demo.export_requests(demo.generate_traces(250, 42, ANCHOR))
    posted = [request.data for request in recorder.requests]
    assert posted == expected
    assert "posted" in capsys.readouterr().out


def test_url_failure_is_reported_with_exit_status_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request: urllib.request.Request, timeout: float) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert demo.main(["--url", "http://127.0.0.1:1", "--traces", "2"]) == 1
    assert "connection refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--url", "ftp://collector.test", "--traces", "1"],
        ["--url", "http:///no-host", "--traces", "1"],
        ["--url", "http://collector.test", "--traces", "0"],
        ["--url", "http://collector.test", "--traces", str(demo.MAX_TRACES + 1)],
        ["--url", "http://collector.test", "--traces", "many"],
        ["--url", "http://collector.test", "--db", "demo.db"],
    ],
)
def test_invalid_arguments_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        demo.main(argv)
    assert excinfo.value.code == 2
