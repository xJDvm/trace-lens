"""HTTP API: OTLP/HTTP JSON trace ingestion and the query endpoints behind the UI.

:func:`create_app` wires the routes to a :class:`Store`. Ingestion reads the body while
streaming it and refuses anything over :data:`tracelens.config.MAX_BODY_BYTES`. Query handlers
are synchronous so that FastAPI runs them in its threadpool. Identifiers and nanosecond values
are serialized as strings, because they can exceed the integer range of JavaScript.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Request
from starlette.concurrency import run_in_threadpool

from tracelens import __version__
from tracelens.config import MAX_BODY_BYTES, MAX_NAME_CHARS
from tracelens.model import AttrValue, Span
from tracelens.otlp import ParseResult, RequestError, parse_export_request
from tracelens.stats import default_bounds, histogram, percentiles
from tracelens.store import Store, TraceSummary
from tracelens.tree import Row, build_tree

DEFAULT_TRACE_LIMIT = 50
MAX_TRACE_LIMIT = 500
LATENCY_SAMPLE_SIZE = 10_000
"""Number of most recent matching spans that the latency statistics are computed over."""
_MAX_INT64 = 2**63 - 1
_NANOS_PER_MS = 1_000_000
_MAX_DURATION_MS = _MAX_INT64 // _NANOS_PER_MS
_TRACE_ID_PATTERN = r"^[0-9a-fA-F]{32}$"
_LATENCY_QUANTILES = (50, 95, 99)


def create_app(store: Store) -> FastAPI:
    """Build the FastAPI application that serves ``store``.

    The ingestion limits are fixed constants rather than settings, so the API takes no
    configuration of its own. The network settings belong to the server process.

    Args:
        store: The span store the endpoints read from and write to.

    Returns:
        The configured application. Its routes are the ones documented in the design: ingestion
        at ``POST /v1/traces`` and the query endpoints under ``/api``.
    """
    app = FastAPI(title="trace-lens", version=__version__)

    @app.post("/v1/traces")
    async def export_traces(request: Request) -> dict[str, object]:
        _check_content_type(request)
        _check_content_encoding(request)
        result = parse_export_request(await _read_body(request))
        if isinstance(result, RequestError):
            raise HTTPException(status_code=400, detail=result.message)
        if result.spans:
            await run_in_threadpool(store.insert_spans, result.spans)
        return _export_response(result)

    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/services")
    def services() -> list[str]:
        return store.services()

    @app.get("/api/traces")
    def list_traces(
        service: Annotated[str | None, Query(min_length=1, max_length=MAX_NAME_CHARS)] = None,
        min_ms: Annotated[int | None, Query(alias="minMs", ge=0, le=_MAX_DURATION_MS)] = None,
        max_ms: Annotated[int | None, Query(alias="maxMs", ge=0, le=_MAX_DURATION_MS)] = None,
        error: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_TRACE_LIMIT)] = DEFAULT_TRACE_LIMIT,
        before: Annotated[int | None, Query(ge=0, le=_MAX_INT64)] = None,
        before_trace_id: Annotated[
            str | None, Query(alias="beforeTraceId", pattern=_TRACE_ID_PATTERN)
        ] = None,
    ) -> dict[str, object]:
        """Newest-first trace summaries, one page at a time.

        The cursor is the pair ``(start, beforeTraceId)`` of the last trace of the previous page,
        sent back as ``before`` and ``beforeTraceId``. The response carries it as
        ``nextBefore`` and ``nextBeforeTraceId``; both are ``null`` unless the page is full.
        ``beforeTraceId`` is only meaningful together with ``before``.
        """
        if before_trace_id is not None and before is None:
            raise HTTPException(status_code=422, detail="beforeTraceId requires before")
        summaries = store.list_traces(
            service,
            _ms_to_ns(min_ms),
            _ms_to_ns(max_ms),
            error,
            limit,
            before,
            None if before_trace_id is None else before_trace_id.lower(),
        )
        last = summaries[-1] if len(summaries) == limit else None
        return {
            "traces": [_summary_json(summary) for summary in summaries],
            "nextBefore": None if last is None else str(last.start_ns),
            "nextBeforeTraceId": None if last is None else last.trace_id,
        }

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: Annotated[str, Path(pattern=_TRACE_ID_PATTERN)]) -> dict[str, object]:
        found = store.get_trace(trace_id.lower())
        if found is None:
            raise HTTPException(status_code=404, detail="trace not found")
        summary, spans = found
        tree = build_tree(spans)
        return {
            "summary": _summary_json(summary),
            "rows": [_row_json(row) for row in tree.rows],
            "orphans": tree.orphans,
        }

    @app.get("/api/stats/latency")
    def latency(
        service: Annotated[str | None, Query(min_length=1, max_length=MAX_NAME_CHARS)] = None,
        name: Annotated[str | None, Query(min_length=1, max_length=MAX_NAME_CHARS)] = None,
    ) -> dict[str, object]:
        samples = sorted(store.latency_samples(service, name, LATENCY_SAMPLE_SIZE))
        p50, p95, p99 = percentiles(samples, _LATENCY_QUANTILES)
        return {
            "count": len(samples),
            "p50": _ns_json(p50),
            "p95": _ns_json(p95),
            "p99": _ns_json(p99),
            "histogram": [
                {"leNs": str(upper), "count": count}
                for _, upper, count in histogram(samples, default_bounds())
            ],
        }

    return app


def _check_content_type(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")


def _check_content_encoding(request: Request) -> None:
    encoding = request.headers.get("content-encoding", "").strip().lower()
    if encoding not in ("", "identity"):
        raise HTTPException(status_code=415, detail="Content-Encoding must be identity")


async def _read_body(request: Request) -> bytes:
    """Read the body, refusing it as soon as it exceeds the limit.

    A declared Content-Length above the limit is refused before any byte is read. The declared
    length is not trusted, so the streamed total is also counted against the limit.
    """
    declared = request.headers.get("content-length", "").strip()
    if declared.isdecimal() and int(declared) > MAX_BODY_BYTES:
        raise _body_too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _body_too_large()
    return bytes(body)


def _body_too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"request body exceeds {MAX_BODY_BYTES} bytes",
    )


def _export_response(result: ParseResult) -> dict[str, object]:
    """The OTLP export response: ``{}`` on full success, otherwise the partial-success report."""
    if result.rejected == 0:
        return {}
    return {
        "partialSuccess": {
            "rejectedSpans": result.rejected,
            "errorMessage": "; ".join(result.errors),
        }
    }


def _ms_to_ns(value: int | None) -> int | None:
    return None if value is None else value * _NANOS_PER_MS


def _ns_json(value: int | None) -> str | None:
    return None if value is None else str(value)


def _summary_json(summary: TraceSummary) -> dict[str, object]:
    return {
        "traceId": summary.trace_id,
        "startNs": str(summary.start_ns),
        "endNs": str(summary.end_ns),
        "durationNs": str(summary.duration_ns),
        "spanCount": summary.span_count,
        "errorCount": summary.error_count,
        "rootService": summary.root_service,
        "rootName": summary.root_name,
    }


def _row_json(row: Row) -> dict[str, object]:
    return {
        **_span_json(row.span),
        "depth": row.depth,
        "offsetNs": str(row.offset_ns),
    }


def _span_json(span: Span) -> dict[str, object]:
    return {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "parentSpanId": span.parent_span_id,
        "service": span.service,
        "name": span.name,
        "kind": span.kind,
        "startNs": str(span.start_ns),
        "endNs": str(span.end_ns),
        "durationNs": str(span.duration_ns),
        "statusCode": span.status_code,
        "statusMessage": span.status_message,
        "attributes": [_attribute_json(key, value) for key, value in span.attributes],
    }


def _attribute_json(key: str, value: AttrValue) -> dict[str, object]:
    """An attribute in the OTLP JSON mapping; 64-bit integers travel as strings."""
    typed: dict[str, object]
    if isinstance(value, bool):
        typed = {"boolValue": value}
    elif isinstance(value, int):
        typed = {"intValue": str(value)}
    elif isinstance(value, float):
        typed = {"doubleValue": value}
    else:
        typed = {"stringValue": value}
    return {"key": key, "value": typed}
