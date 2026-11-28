"""Tests for the HTTP API, driven through FastAPI's ``TestClient`` against an in-memory store."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tracelens import config
from tracelens.api import LATENCY_SAMPLE_SIZE, create_app
from tracelens.model import Span
from tracelens.store import Store

TRACE = "0af7651916cd43dd8448eb211c80319c"
OTHER_TRACE = "1bf7651916cd43dd8448eb211c80319d"
UNKNOWN_TRACE = "2cf7651916cd43dd8448eb211c80319e"
ZERO_TRACE = "0" * 32
START_NS = 1_700_000_000_000_000_000
"""A realistic epoch timestamp, above 2^53, so that string serialization is exercised."""
MS = 1_000_000
ERROR_STATUS = 2
_PAD_PREFIX = b'{"resourceSpans": [], "pad": "'
_PAD_SUFFIX = b'"}'
_CHUNK = 64 * 1024


@pytest.fixture
def store() -> Iterator[Store]:
    db = Store(":memory:")
    yield db
    db.close()


@pytest.fixture
def client(store: Store) -> Iterator[TestClient]:
    with TestClient(create_app(store)) as test_client:
        yield test_client


def _span(
    trace: str,
    span_id: str,
    *,
    parent: str | None = None,
    name: str = "op",
    start_ns: int = START_NS,
    duration_ns: int = MS,
    status_code: int = 0,
    attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    span: dict[str, object] = {
        "traceId": trace,
        "spanId": span_id,
        "name": name,
        "kind": 2,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "attributes": attributes or [],
        "status": {"code": status_code},
    }
    if parent is not None:
        span["parentSpanId"] = parent
    return span


def _export_body(service: str, spans: list[dict[str, object]]) -> bytes:
    document = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }
    return json.dumps(document).encode("utf-8")


def _post(client: TestClient, body: bytes, **headers: str) -> httpx.Response:
    merged = {"Content-Type": "application/json", **headers}
    return client.post("/v1/traces", content=body, headers=merged)


def _ingest(client: TestClient, service: str, spans: list[dict[str, object]]) -> None:
    response = _post(client, _export_body(service, spans))
    assert response.status_code == 200, response.text
    assert response.json() == {}


def _padded(size: int) -> bytes:
    """Valid export-free JSON of exactly ``size`` bytes."""
    return _PAD_PREFIX + b"x" * (size - len(_PAD_PREFIX) - len(_PAD_SUFFIX)) + _PAD_SUFFIX


def _chunks(body: bytes) -> Iterable[bytes]:
    """The body as a stream of chunks, so the request has no Content-Length header."""
    return (body[start : start + _CHUNK] for start in range(0, len(body), _CHUNK))


# Ingestion: headers ----------------------------------------------------------------------------


@pytest.mark.parametrize("content_type", ["text/plain", "application/xml", "application/jsonx"])
def test_non_json_content_type_is_415(client: TestClient, content_type: str) -> None:
    response = _post(client, _padded(64), **{"Content-Type": content_type})

    assert response.status_code == 415


def test_missing_content_type_is_415(client: TestClient) -> None:
    response = client.post("/v1/traces", content=_padded(64))

    assert response.status_code == 415


def test_content_type_parameters_are_allowed(client: TestClient) -> None:
    response = _post(client, _padded(64), **{"Content-Type": "Application/JSON; charset=utf-8"})

    assert response.status_code == 200


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip"])
def test_content_encoding_other_than_identity_is_415(client: TestClient, encoding: str) -> None:
    response = _post(client, _padded(64), **{"Content-Encoding": encoding})

    assert response.status_code == 415


def test_identity_content_encoding_is_accepted(client: TestClient) -> None:
    response = _post(client, _padded(64), **{"Content-Encoding": "identity"})

    assert response.status_code == 200


# Ingestion: body size --------------------------------------------------------------------------


def test_body_at_size_limit_is_accepted_with_content_length(client: TestClient) -> None:
    response = _post(client, _padded(config.MAX_BODY_BYTES))

    assert response.status_code == 200


def test_body_one_byte_over_limit_is_413_with_content_length(client: TestClient) -> None:
    response = _post(client, _padded(config.MAX_BODY_BYTES + 1))

    assert response.status_code == 413


def test_streamed_body_at_size_limit_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/v1/traces",
        content=_chunks(_padded(config.MAX_BODY_BYTES)),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_streamed_body_one_byte_over_limit_is_413(client: TestClient) -> None:
    """Without Content-Length the limit is enforced on the bytes actually received."""
    response = client.post(
        "/v1/traces",
        content=_chunks(_padded(config.MAX_BODY_BYTES + 1)),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_declared_length_over_limit_is_413_before_reading(client: TestClient) -> None:
    response = _post(client, b"{}", **{"Content-Length": str(config.MAX_BODY_BYTES + 1)})

    assert response.status_code == 413


# Ingestion: decoding and partial success -------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"not json",
        b"[]",
        b'{"resourceSpans": 3}',
        b'{"resourceSpans": [{"resource": 1}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": {}}]}]}',
        b'{"resourceSpans": [], "x": NaN}',
        b"\xff\xfe",
    ],
)
def test_malformed_body_is_400(client: TestClient, body: bytes) -> None:
    response = _post(client, body)

    assert response.status_code == 400
    assert "detail" in response.json()


def test_full_success_returns_empty_export_response(client: TestClient) -> None:
    response = _post(client, _export_body("api", [_span(TRACE, "0000000000000001")]))

    assert response.status_code == 200
    assert response.json() == {}


def test_partial_success_reports_rejected_spans_and_stores_the_good_ones(
    client: TestClient,
) -> None:
    good = _span(TRACE, "0000000000000001")
    bad = _span(ZERO_TRACE, "0000000000000002")

    response = _post(client, _export_body("api", [good, bad]))

    assert response.status_code == 200
    partial = response.json()["partialSuccess"]
    assert partial["rejectedSpans"] == 1
    assert "traceId" in partial["errorMessage"]
    detail = client.get(f"/api/traces/{TRACE}").json()
    assert len(detail["rows"]) == 1
    assert client.get(f"/api/traces/{ZERO_TRACE}").status_code == 404


def test_resending_a_batch_is_idempotent(client: TestClient) -> None:
    body = _export_body("api", [_span(TRACE, "0000000000000001")])

    assert _post(client, body).status_code == 200
    assert _post(client, body).status_code == 200

    assert len(client.get(f"/api/traces/{TRACE}").json()["rows"]) == 1


# Queries: round trip, tree and identifiers -----------------------------------------------------


def test_ingest_then_list_then_get_round_trip(client: TestClient) -> None:
    _ingest(
        client,
        "api",
        [
            _span(TRACE, "0000000000000001", name="GET /", duration_ns=10 * MS),
            _span(
                TRACE,
                "0000000000000002",
                parent="0000000000000001",
                name="db",
                start_ns=START_NS + 2 * MS,
                duration_ns=3 * MS,
                status_code=ERROR_STATUS,
                attributes=[
                    {"key": "db.rows", "value": {"intValue": "9007199254740993"}},
                    {"key": "cache", "value": {"boolValue": False}},
                    {"key": "ratio", "value": {"doubleValue": 0.5}},
                ],
            ),
        ],
    )

    listing = client.get("/api/traces").json()
    detail = client.get(f"/api/traces/{TRACE}").json()

    assert listing["nextBefore"] is None
    assert listing["traces"] == [
        {
            "traceId": TRACE,
            "startNs": str(START_NS),
            "endNs": str(START_NS + 10 * MS),
            "durationNs": str(10 * MS),
            "spanCount": 2,
            "errorCount": 1,
            "rootService": "api",
            "rootName": "GET /",
        }
    ]
    assert detail["summary"] == listing["traces"][0]
    assert detail["orphans"] == 0
    root, child = detail["rows"]
    assert root["spanId"] == "0000000000000001"
    assert root["parentSpanId"] is None
    assert root["depth"] == 0
    assert root["offsetNs"] == "0"
    assert child["depth"] == 1
    assert child["parentSpanId"] == "0000000000000001"
    assert child["offsetNs"] == str(2 * MS)
    assert child["startNs"] == str(START_NS + 2 * MS)
    assert child["durationNs"] == str(3 * MS)
    assert child["statusCode"] == ERROR_STATUS
    assert child["attributes"] == [
        {"key": "service.name", "value": {"stringValue": "api"}},
        {"key": "db.rows", "value": {"intValue": "9007199254740993"}},
        {"key": "cache", "value": {"boolValue": False}},
        {"key": "ratio", "value": {"doubleValue": 0.5}},
    ]


def test_uppercase_trace_id_is_accepted(client: TestClient) -> None:
    _ingest(client, "api", [_span(TRACE, "0000000000000001")])

    response = client.get(f"/api/traces/{TRACE.upper()}")

    assert response.status_code == 200
    assert response.json()["summary"]["traceId"] == TRACE


def test_unknown_trace_is_404(client: TestClient) -> None:
    response = client.get(f"/api/traces/{UNKNOWN_TRACE}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "trace_id",
    ["abc", "g" * 32, "0" * 33, f"{TRACE}%0A", f"{TRACE}%20"],
)
def test_malformed_trace_id_is_422(client: TestClient, trace_id: str) -> None:
    response = client.get(f"/api/traces/{trace_id}")

    assert response.status_code == 422


def test_orphan_count_is_reported(client: TestClient) -> None:
    _ingest(
        client,
        "api",
        [_span(TRACE, "0000000000000002", parent="0000000000000009")],
    )

    detail = client.get(f"/api/traces/{TRACE}").json()

    assert detail["orphans"] == 1
    assert detail["rows"][0]["depth"] == 0


# Queries: trace list filters and cursor --------------------------------------------------------


def test_list_is_newest_first_and_pages_with_next_before(client: TestClient) -> None:
    for index in range(5):
        _ingest(
            client,
            "api",
            [_span(f"{index + 1:032x}", "0000000000000001", start_ns=START_NS + index)],
        )

    first = client.get("/api/traces", params={"limit": 2}).json()
    second = _next_page(client, first, limit=2)
    third = _next_page(client, second, limit=2)

    starts = [trace["startNs"] for page in (first, second, third) for trace in page["traces"]]
    assert starts == [str(START_NS + index) for index in (4, 3, 2, 1, 0)]
    assert third["nextBefore"] is None
    assert client.get("/api/traces", params={"before": START_NS}).json()["traces"] == []


def _next_page(client: TestClient, page: dict[str, Any], limit: int) -> dict[str, Any]:
    """Fetch the page that follows ``page`` by sending back its cursor."""
    params = {
        "limit": limit,
        "before": page["nextBefore"],
        "beforeTraceId": page["nextBeforeTraceId"],
    }
    return client.get("/api/traces", params=params).json()


def _all_trace_ids(client: TestClient, limit: int) -> list[str]:
    """Walk every page of the trace list, following the cursor until it ends."""
    page = client.get("/api/traces", params={"limit": limit}).json()
    ids = [trace["traceId"] for trace in page["traces"]]
    while page["nextBefore"] is not None:
        page = _next_page(client, page, limit)
        ids.extend(trace["traceId"] for trace in page["traces"])
    return ids


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 6])
def test_pages_neither_lose_nor_repeat_traces_sharing_a_start(
    client: TestClient, limit: int
) -> None:
    """Several traces with the same start time straddle page boundaries for every page size."""
    tied = [f"{index:032x}" for index in range(1, 8)]
    for trace in tied:
        _ingest(client, "api", [_span(trace, "0000000000000001", start_ns=START_NS)])
    _ingest(client, "api", [_span(OTHER_TRACE, "0000000000000001", start_ns=START_NS + 1)])

    ids = _all_trace_ids(client, limit)

    assert len(ids) == len(set(ids)) == len(tied) + 1
    assert set(ids) == {*tied, OTHER_TRACE}
    assert ids[0] == OTHER_TRACE


def test_before_trace_id_without_before_is_422(client: TestClient) -> None:
    response = client.get("/api/traces", params={"beforeTraceId": TRACE})

    assert response.status_code == 422


def test_malformed_before_trace_id_is_422(client: TestClient) -> None:
    response = client.get("/api/traces", params={"before": 1, "beforeTraceId": "xyz"})

    assert response.status_code == 422


def test_before_trace_id_accepts_uppercase(client: TestClient) -> None:
    for trace in (TRACE, OTHER_TRACE):
        _ingest(client, "api", [_span(trace, "0000000000000001", start_ns=START_NS)])

    response = client.get(
        "/api/traces",
        params={"before": START_NS, "beforeTraceId": OTHER_TRACE.upper()},
    )

    assert [trace["traceId"] for trace in response.json()["traces"]] == [TRACE]


def test_list_without_more_pages_has_null_cursor(client: TestClient) -> None:
    _ingest(client, "api", [_span(TRACE, "0000000000000001")])

    listing = client.get("/api/traces", params={"limit": 2}).json()

    assert len(listing["traces"]) == 1
    assert listing["nextBefore"] is None


def test_list_filters_by_service_error_and_duration(client: TestClient) -> None:
    _ingest(client, "api", [_span(TRACE, "0000000000000001", duration_ns=1 * MS)])
    _ingest(
        client,
        "payments",
        [_span(OTHER_TRACE, "0000000000000001", duration_ns=5 * MS, status_code=ERROR_STATUS)],
    )

    def ids(params: dict[str, Any]) -> list[str]:
        response = client.get("/api/traces", params=params)
        assert response.status_code == 200
        return [trace["traceId"] for trace in response.json()["traces"]]

    assert ids({"service": "payments"}) == [OTHER_TRACE]
    assert ids({"service": "missing"}) == []
    assert ids({"error": "true"}) == [OTHER_TRACE]
    assert ids({"error": "false"}) == [TRACE]
    assert ids({"minMs": 2}) == [OTHER_TRACE]
    assert ids({"maxMs": 2}) == [TRACE]
    assert ids({"minMs": 1, "maxMs": 5, "error": "false"}) == [TRACE]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 10**6},
        {"limit": 501},
        {"limit": -1},
        {"limit": "many"},
        {"before": -1},
        {"minMs": -1},
        {"maxMs": 9_223_372_036_855},
        {"service": ""},
        {"service": "s" * (config.MAX_NAME_CHARS + 1)},
        {"error": "maybe"},
    ],
)
def test_out_of_bounds_query_is_422(client: TestClient, params: dict[str, object]) -> None:
    response = client.get("/api/traces", params=params)

    assert response.status_code == 422


def test_limit_at_maximum_is_accepted(client: TestClient) -> None:
    response = client.get("/api/traces", params={"limit": 500})

    assert response.status_code == 200


# Queries: services and latency -----------------------------------------------------------------


def test_services_are_distinct_and_sorted(client: TestClient) -> None:
    _ingest(client, "checkout", [_span(TRACE, "0000000000000001")])
    _ingest(client, "api", [_span(TRACE, "0000000000000002")])
    _ingest(client, "api", [_span(OTHER_TRACE, "0000000000000001")])

    assert client.get("/api/services").json() == ["api", "checkout"]


def test_healthz(client: TestClient) -> None:
    response = client.get("/api/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_latency_of_empty_store_has_null_percentiles(client: TestClient) -> None:
    stats = client.get("/api/stats/latency").json()

    assert stats["count"] == 0
    assert stats["p50"] is None
    assert stats["p95"] is None
    assert stats["p99"] is None
    assert sum(bucket["count"] for bucket in stats["histogram"]) == 0


def test_latency_percentiles_and_histogram(client: TestClient) -> None:
    spans = [
        _span(f"{index:032x}", "0000000000000001", duration_ns=index, name="op")
        for index in range(1, 101)
    ]
    _ingest(client, "api", spans)
    _ingest(client, "api", [_span(OTHER_TRACE, "0000000000000001", name="other")])

    stats = client.get("/api/stats/latency", params={"name": "op"}).json()

    assert stats["count"] == 100
    assert stats["p50"] == "50"
    assert stats["p95"] == "95"
    assert stats["p99"] == "99"
    assert sum(bucket["count"] for bucket in stats["histogram"]) == 100
    assert stats["histogram"][0]["count"] == 100
    assert all(isinstance(bucket["leNs"], str) for bucket in stats["histogram"])


def test_latency_filters_by_service(client: TestClient) -> None:
    _ingest(client, "api", [_span(TRACE, "0000000000000001", duration_ns=1 * MS)])
    _ingest(client, "db", [_span(OTHER_TRACE, "0000000000000001", duration_ns=7 * MS)])

    stats = client.get("/api/stats/latency", params={"service": "db"}).json()

    assert stats["count"] == 1
    assert stats["p50"] == str(7 * MS)


def test_latency_uses_only_the_most_recent_sample_window(client: TestClient, store: Store) -> None:
    window = LATENCY_SAMPLE_SIZE
    store.insert_spans(
        Span(
            trace_id=f"{index:032x}",
            span_id="0000000000000001",
            parent_span_id=None,
            service="api",
            name="op",
            kind=2,
            start_ns=START_NS + index,
            end_ns=START_NS + index + MS,
            status_code=0,
            status_message="",
            attributes=(),
        )
        for index in range(1, window + 6)
    )

    stats = client.get("/api/stats/latency").json()

    assert stats["count"] == window


def test_latency_rejects_empty_name_filter(client: TestClient) -> None:
    response = client.get("/api/stats/latency", params={"name": ""})

    assert response.status_code == 422


# Queries: service map --------------------------------------------------------------------------


def _service_map(client: TestClient, **params: object) -> dict[str, Any]:
    response = client.get("/api/service-map", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _chain_trace(client: TestClient, trace: str, start_ns: int, error: int = 0) -> None:
    """gateway calls orders (which may fail), orders calls db; each service in its own batch."""
    _ingest(client, "gateway", [_span(trace, "0000000000000001", start_ns=start_ns)])
    _ingest(
        client,
        "orders",
        [
            _span(
                trace,
                "0000000000000002",
                parent="0000000000000001",
                start_ns=start_ns,
                status_code=error,
            )
        ],
    )
    _ingest(
        client,
        "db",
        [_span(trace, "0000000000000003", parent="0000000000000002", start_ns=start_ns)],
    )


def test_service_map_of_empty_store_is_empty(client: TestClient) -> None:
    assert _service_map(client) == {"nodes": [], "edges": []}


def test_service_map_has_nodes_with_incoming_totals_and_sorted_edges(client: TestClient) -> None:
    _chain_trace(client, TRACE, START_NS, error=ERROR_STATUS)

    body = _service_map(client)

    assert set(body) == {"nodes", "edges"}
    assert body["edges"] == [
        {"caller": "gateway", "callee": "orders", "calls": 1, "errors": 1},
        {"caller": "orders", "callee": "db", "calls": 1, "errors": 0},
    ]
    assert body["nodes"] == [
        {"service": "db", "calls": 1, "errors": 0},
        {"service": "gateway", "calls": 0, "errors": 0},
        {"service": "orders", "calls": 1, "errors": 1},
    ]


def test_service_map_lists_root_service_without_edges(client: TestClient) -> None:
    _ingest(client, "solo", [_span(TRACE, "0000000000000001")])

    assert _service_map(client) == {
        "nodes": [{"service": "solo", "calls": 0, "errors": 0}],
        "edges": [],
    }


def test_service_map_sums_calls_over_traces(client: TestClient) -> None:
    _chain_trace(client, TRACE, START_NS, error=ERROR_STATUS)
    _chain_trace(client, OTHER_TRACE, START_NS + 1)

    body = _service_map(client)

    assert body["edges"] == [
        {"caller": "gateway", "callee": "orders", "calls": 2, "errors": 1},
        {"caller": "orders", "callee": "db", "calls": 2, "errors": 0},
    ]
    assert {"service": "orders", "calls": 2, "errors": 1} in body["nodes"]


def test_service_map_since_ns_skips_older_traces(client: TestClient) -> None:
    _chain_trace(client, TRACE, START_NS)
    _ingest(client, "old", [_span(OTHER_TRACE, "0000000000000001", start_ns=START_NS - 1)])

    body = _service_map(client, sinceNs=START_NS)

    assert [node["service"] for node in body["nodes"]] == ["db", "gateway", "orders"]
    assert body["edges"][0]["calls"] == 1
    assert _service_map(client, sinceNs=START_NS + 1) == {"nodes": [], "edges": []}


def test_service_map_traces_limit_keeps_most_recent(client: TestClient) -> None:
    _ingest(client, "old", [_span(TRACE, "0000000000000001", start_ns=START_NS)])
    _chain_trace(client, OTHER_TRACE, START_NS + 1)

    body = _service_map(client, traces=1)

    assert [node["service"] for node in body["nodes"]] == ["db", "gateway", "orders"]
    assert "old" not in {node["service"] for node in body["nodes"]}


@pytest.mark.parametrize("value", ["0", "9223372036854775807"])
def test_service_map_accepts_valid_since_ns(client: TestClient, value: str) -> None:
    assert _service_map(client, sinceNs=value) == {"nodes": [], "edges": []}


@pytest.mark.parametrize(
    "value", ["", "-1", "1.5", "1e3", " 1", "0x1f", "1" * 20, "9223372036854775808"]
)
def test_malformed_or_overflowing_since_ns_is_422(client: TestClient, value: str) -> None:
    response = client.get("/api/service-map", params={"sinceNs": value})

    assert response.status_code == 422


@pytest.mark.parametrize("traces", [0, -1, 1001, "many"])
def test_out_of_range_service_map_traces_is_422(client: TestClient, traces: object) -> None:
    response = client.get("/api/service-map", params={"traces": traces})

    assert response.status_code == 422


@pytest.mark.parametrize("traces", [1, 1000])
def test_service_map_traces_at_bounds_is_accepted(client: TestClient, traces: int) -> None:
    assert _service_map(client, traces=traces) == {"nodes": [], "edges": []}
