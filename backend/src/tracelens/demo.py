"""Seeded load generator that simulates a microservice system and exports its traces.

Run ``python -m tracelens.demo --url http://127.0.0.1:4318`` to post the traces to a running
server, or ``--db PATH`` to write them straight into a SQLite database.

Topology: ``web-frontend`` calls ``api-gateway``, which calls ``auth`` and ``catalog`` (or
``checkout``). ``catalog`` reads ``redis`` and sometimes ``postgres``; ``checkout`` calls
``payments``; ``auth`` reads ``postgres`` when issuing tokens.

The random numbers come from :class:`random.Random` and only drive this simulation. They are not
cryptographic and nothing generated here is a secret. With the default fixed timeline, the same
seed and trace count produce byte-identical OTLP payloads. ``--now`` anchors the timeline to the
current time instead, so its timestamps differ between runs.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from random import Random

from tracelens.model import AttrValue, Span
from tracelens.store import Store

DEFAULT_SEED = 42
DEFAULT_TRACES = 300
DEFAULT_ANCHOR_NS = 1_700_000_000_000_000_000
"""Start of the fixed timeline (2023-11-14T22:13:20Z), used unless ``--now`` is given."""
TRACE_SPACING_NS = 2_000_000_000
"""Distance between the nominal starts of consecutive traces."""
MAX_TRACES = 100_000
TRACES_PER_REQUEST = 100
"""Traces per POST. Each trace has at most six spans, far below the request limits."""
REQUEST_TIMEOUT_S = 5.0
SLOW_FACTOR = 6.0
"""Latency multiplier applied to the slow tail of an operation."""

_NS_PER_MS = 1_000_000
_INTERNAL_KIND = 1
_SERVER_KIND = 2
_CLIENT_KIND = 3
_STATUS_UNSET = 0
_STATUS_ERROR = 2
_DEFAULT_ERROR = "internal error"
_TRACE_SCOPE = "tracelens.demo"
_INGEST_PATH = "/v1/traces"
_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class _Call:
    """A span template: one operation of one service, its latency model and the calls it makes.

    Each child is made with its own probability, which models cache hits and optional steps.
    ``error_rate`` is the chance that the operation fails by itself. A failed child fails its
    caller, so errors propagate up the trace as they do in a real request.
    """

    service: str
    name: str
    kind: int
    median_ms: float
    sigma: float
    attributes: tuple[tuple[str, AttrValue], ...] = ()
    children: tuple[tuple[float, _Call], ...] = ()
    error_rate: float = 0.0
    error_message: str = _DEFAULT_ERROR
    slow_rate: float = 0.0


_REDIS_GET = _Call(
    service="redis",
    name="GET catalog:page",
    kind=_CLIENT_KIND,
    median_ms=0.4,
    sigma=0.3,
    attributes=(("db.system", "redis"),),
)
_POSTGRES_PRODUCTS = _Call(
    service="postgres",
    name="SELECT products",
    kind=_CLIENT_KIND,
    median_ms=3.0,
    sigma=0.5,
    attributes=(("db.system", "postgresql"),),
    slow_rate=0.05,
)
_POSTGRES_USERS = _Call(
    service="postgres",
    name="SELECT users",
    kind=_CLIENT_KIND,
    median_ms=2.0,
    sigma=0.4,
    attributes=(("db.system", "postgresql"),),
)
_CATALOG = _Call(
    service="catalog",
    name="list products",
    kind=_SERVER_KIND,
    median_ms=1.5,
    sigma=0.3,
    children=((1.0, _REDIS_GET), (0.3, _POSTGRES_PRODUCTS)),
    slow_rate=0.06,
)
_AUTH_VERIFY = _Call(
    service="auth",
    name="verify token",
    kind=_SERVER_KIND,
    median_ms=0.9,
    sigma=0.3,
    error_rate=0.004,
    error_message="token rejected",
)
_AUTH_ISSUE = _Call(
    service="auth",
    name="issue token",
    kind=_SERVER_KIND,
    median_ms=8.0,
    sigma=0.3,
    children=((1.0, _POSTGRES_USERS),),
)
_PAYMENTS = _Call(
    service="payments",
    name="POST /charge",
    kind=_SERVER_KIND,
    median_ms=180.0,
    sigma=0.4,
    attributes=(("payment.method", "card"),),
    error_rate=0.03,
    error_message="payment provider timeout",
)
_CHECKOUT = _Call(
    service="checkout",
    name="place order",
    kind=_SERVER_KIND,
    median_ms=6.0,
    sigma=0.3,
    children=((1.0, _PAYMENTS),),
)
_GATEWAY_PRODUCTS = _Call(
    service="api-gateway",
    name="GET /api/products",
    kind=_SERVER_KIND,
    median_ms=1.0,
    sigma=0.25,
    children=((1.0, _AUTH_VERIFY), (1.0, _CATALOG)),
)
_GATEWAY_CHECKOUT = _Call(
    service="api-gateway",
    name="POST /api/checkout",
    kind=_SERVER_KIND,
    median_ms=1.2,
    sigma=0.25,
    children=((1.0, _AUTH_VERIFY), (1.0, _CHECKOUT)),
)
_GATEWAY_LOGIN = _Call(
    service="api-gateway",
    name="POST /api/login",
    kind=_SERVER_KIND,
    median_ms=1.0,
    sigma=0.25,
    children=((1.0, _AUTH_ISSUE),),
)
_WEB_BROWSE = _Call(
    service="web-frontend",
    name="GET /products",
    kind=_SERVER_KIND,
    median_ms=0.8,
    sigma=0.2,
    attributes=(("http.route", "/products"),),
    children=((1.0, _GATEWAY_PRODUCTS),),
)
_WEB_CHECKOUT = _Call(
    service="web-frontend",
    name="POST /checkout",
    kind=_SERVER_KIND,
    median_ms=0.9,
    sigma=0.2,
    attributes=(("http.route", "/checkout"),),
    children=((1.0, _GATEWAY_CHECKOUT),),
)
_WEB_LOGIN = _Call(
    service="web-frontend",
    name="POST /login",
    kind=_SERVER_KIND,
    median_ms=0.9,
    sigma=0.2,
    attributes=(("http.route", "/login"),),
    children=((1.0, _GATEWAY_LOGIN),),
)
_FLOWS: tuple[_Call, ...] = (_WEB_BROWSE, _WEB_CHECKOUT, _WEB_LOGIN)
_FLOW_WEIGHTS: tuple[int, ...] = (6, 2, 2)


def generate_traces(count: int, seed: int, anchor_ns: int) -> list[list[Span]]:
    """Simulate ``count`` request traces and return the spans of each trace.

    Trace ``i`` nominally starts at ``anchor_ns + i * TRACE_SPACING_NS``, shifted by a seeded
    jitter of less than half the spacing. The result depends only on ``count``, ``seed`` and
    ``anchor_ns``, so the same arguments always give the same spans.

    Raises:
        ValueError: If ``anchor_ns`` is not positive, since span timestamps must be positive.
    """
    if anchor_ns <= 0:
        raise ValueError("anchor_ns must be positive")
    rng = Random(seed)
    traces: list[list[Span]] = []
    for index in range(count):
        start_ns = anchor_ns + index * TRACE_SPACING_NS + rng.randrange(TRACE_SPACING_NS // 2)
        flow = rng.choices(_FLOWS, weights=_FLOW_WEIGHTS)[0]
        trace_id = _random_hex(rng, 32)
        spans: list[Span] = []
        _emit(flow, start_ns, None, trace_id, rng, spans)
        traces.append(spans)
    return traces


def export_requests(traces: Sequence[Sequence[Span]]) -> list[bytes]:
    """Encode ``traces`` as OTLP/HTTP JSON ``ExportTraceServiceRequest`` bodies.

    Each body holds at most ``TRACES_PER_REQUEST`` traces. Spans are grouped into one
    ``resourceSpans`` entry per service, with the service name as the resource attribute.
    """
    bodies: list[bytes] = []
    for start in range(0, len(traces), TRACES_PER_REQUEST):
        chunk = [span for trace in traces[start : start + TRACES_PER_REQUEST] for span in trace]
        bodies.append(_encode(chunk))
    return bodies


def _emit(
    call: _Call,
    start_ns: int,
    parent_span_id: str | None,
    trace_id: str,
    rng: Random,
    out: list[Span],
) -> tuple[int, str | None]:
    """Append the spans of ``call`` and of its downstream calls to ``out``.

    Returns the end time of ``call`` and its error message, or ``None`` when it succeeded. The
    own time of the operation is split around its downstream calls, so every child starts and
    ends inside its parent. A failed child stops the calls its caller would have made next.
    """
    span_id = _random_hex(rng, 16)
    own_ns = _sample_duration_ns(call, rng)
    before_ns = own_ns // 2
    cursor = start_ns + before_ns
    error: str | None = None
    if rng.random() < call.error_rate:
        error = call.error_message
    else:
        for probability, child in call.children:
            if rng.random() < probability:
                cursor, child_error = _emit(child, cursor, span_id, trace_id, rng, out)
                if child_error is not None:
                    error = f"{child.service} failed"
                    break
    end_ns = cursor + own_ns - before_ns
    out.append(
        Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            service=call.service,
            name=call.name,
            kind=call.kind,
            start_ns=start_ns,
            end_ns=end_ns,
            status_code=_STATUS_ERROR if error is not None else _STATUS_UNSET,
            status_message=error or "",
            attributes=call.attributes,
        )
    )
    return end_ns, error


def _sample_duration_ns(call: _Call, rng: Random) -> int:
    """Draw a log-normal duration around the median, with the slow tail applied sometimes."""
    milliseconds = rng.lognormvariate(math.log(call.median_ms), call.sigma)
    if rng.random() < call.slow_rate:
        milliseconds *= SLOW_FACTOR
    return max(1, round(milliseconds * _NS_PER_MS))


def _random_hex(rng: Random, digits: int) -> str:
    """Return a random lowercase hex id of ``digits`` characters that is not all zeros."""
    return f"{rng.randrange(1, 16**digits):0{digits}x}"


def _encode(spans: Sequence[Span]) -> bytes:
    by_service: dict[str, list[Span]] = {}
    for span in spans:
        by_service.setdefault(span.service, []).append(span)
    resource_spans = [
        {
            "resource": {"attributes": [_attribute_json("service.name", service)]},
            "scopeSpans": [
                {
                    "scope": {"name": _TRACE_SCOPE},
                    "spans": [_span_json(span) for span in group],
                }
            ],
        }
        for service, group in by_service.items()
    ]
    body = json.dumps({"resourceSpans": resource_spans}, separators=(",", ":"))
    return body.encode("utf-8")


def _span_json(span: Span) -> dict[str, object]:
    status: dict[str, object] = {"code": span.status_code}
    if span.status_message:
        status["message"] = span.status_message
    body: dict[str, object] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": span.kind,
        "startTimeUnixNano": str(span.start_ns),
        "endTimeUnixNano": str(span.end_ns),
        "attributes": [_attribute_json(key, value) for key, value in span.attributes],
        "status": status,
    }
    if span.parent_span_id is not None:
        body["parentSpanId"] = span.parent_span_id
    return body


def _attribute_json(key: str, value: AttrValue) -> dict[str, object]:
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


def _post(endpoint: str, body: bytes) -> None:
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        response.read(_MAX_RESPONSE_BYTES)


def _write_db(path: str, traces: Sequence[Sequence[Span]]) -> int:
    store = Store(path)
    try:
        return store.insert_spans(span for trace in traces for span in trace)
    finally:
        store.close()


def _http_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise argparse.ArgumentTypeError("expected an http:// or https:// URL with a host")
    return value.rstrip("/")


def _trace_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if not 1 <= count <= MAX_TRACES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_TRACES}")
    return count


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tracelens.demo",
        description="Generate seeded microservice traces and send them to trace-lens.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--url",
        type=_http_url,
        help="server base URL; the traces are POSTed to <url>/v1/traces",
    )
    target.add_argument("--db", metavar="PATH", help="SQLite database file to write directly")
    parser.add_argument(
        "--traces",
        type=_trace_count,
        default=DEFAULT_TRACES,
        help=f"number of traces to generate (default {DEFAULT_TRACES})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"random seed; the same seed gives the same traces (default {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="anchor the timestamps to the current time instead of a fixed timeline",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the traces described by ``argv`` and deliver them.

    Args:
        argv: Command-line arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` if the traces could not be posted or written.
    """
    args = _parse_args(argv)
    anchor_ns = time.time_ns() - args.traces * TRACE_SPACING_NS if args.now else DEFAULT_ANCHOR_NS
    traces = generate_traces(args.traces, args.seed, anchor_ns)
    span_total = sum(len(trace) for trace in traces)
    try:
        if args.db is not None:
            stored = _write_db(args.db, traces)
            print(f"stored {stored} new spans from {len(traces)} traces in {args.db}")
        else:
            endpoint = f"{args.url}{_INGEST_PATH}"
            for body in export_requests(traces):
                _post(endpoint, body)
            print(f"posted {span_total} spans from {len(traces)} traces to {endpoint}")
    except (OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
