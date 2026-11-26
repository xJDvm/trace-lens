"""Tests for OTLP/HTTP JSON export parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from tracelens.config import MAX_JSON_DEPTH
from tracelens.model import Span
from tracelens.otlp import (
    DEFAULT_SERVICE_NAME,
    ParseResult,
    RequestError,
    parse_export_request,
)

FIXTURES = Path(__file__).parent / "fixtures"
TRACE_ID = "5b8efff798038103d269b633813fc60c"
SPAN_ID = "eee19b7ec3c1b174"
MAX_INT64 = 2**63 - 1
MIN_INT64 = -(2**63)
_DELETE = object()

_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX16 = re.compile(r"[0-9a-f]{16}")


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _parsed(raw: bytes) -> ParseResult:
    result = parse_export_request(raw)
    assert isinstance(result, ParseResult), result
    return result


def _base_span() -> dict[str, object]:
    """A span that passes every check; tests mutate one field at a time."""
    return {
        "traceId": TRACE_ID,
        "spanId": SPAN_ID,
        "name": "op",
        "kind": 1,
        "startTimeUnixNano": "1000",
        "endTimeUnixNano": "2000",
        "attributes": [],
        "status": {"code": 0},
    }


def _service(name: str) -> dict[str, object]:
    return {"key": "service.name", "value": {"stringValue": name}}


def _request(*spans: object, resource_attributes: list[object] | None = None) -> bytes:
    if resource_attributes is None:
        resource_attributes = [_service("catalog")]
    body = {
        "resourceSpans": [
            {
                "resource": {"attributes": resource_attributes},
                "scopeSpans": [{"spans": list(spans)}],
            }
        ]
    }
    return json.dumps(body).encode("utf-8")


def _span_with_attribute(attribute: object) -> dict[str, object]:
    span = _base_span()
    span["attributes"] = [attribute]
    return span


def _attribute_value(value: object) -> object:
    """Decode one attribute whose value is ``value`` and return the stored value."""
    result = _parsed(_request(_span_with_attribute({"key": "k", "value": value})))
    assert len(result.spans) == 1, result.errors
    return result.spans[0].attributes[-1][1]


def test_two_service_fixture_yields_every_span() -> None:
    result = _parsed(_fixture_bytes("export_two_services.json"))

    assert result.rejected == 0
    assert result.errors == []
    assert len(result.spans) == 5
    assert {span.service for span in result.spans} == {"api-gateway", "payments"}


def test_fixture_parent_links_cross_services() -> None:
    spans = {
        span.span_id: span for span in _parsed(_fixture_bytes("export_two_services.json")).spans
    }

    assert spans["eee19b7ec3c1b174"].parent_span_id is None
    assert spans["a1b2c3d4e5f60718"].parent_span_id == "eee19b7ec3c1b174"
    assert spans["0f0e0d0c0b0a0908"].parent_span_id == "a1b2c3d4e5f60718"
    assert spans["1122334455667788"].parent_span_id == "0f0e0d0c0b0a0908"


def test_fixture_span_fields_and_attributes_are_decoded() -> None:
    spans = {
        span.span_id: span for span in _parsed(_fixture_bytes("export_two_services.json")).spans
    }
    checkout = spans["eee19b7ec3c1b174"]

    assert checkout == Span(
        trace_id=TRACE_ID,
        span_id="eee19b7ec3c1b174",
        parent_span_id=None,
        service="api-gateway",
        name="GET /checkout",
        kind=2,
        start_ns=1_700_000_000_000_000_000,
        end_ns=1_700_000_000_250_000_000,
        status_code=1,
        status_message="",
        attributes=(
            ("service.name", "api-gateway"),
            ("service.version", "1.4.2"),
            ("deployment.replicas", 3),
            ("http.method", "GET"),
            ("http.status_code", 200),
            ("http.response_content_length", 1024.5),
            ("http.retry", False),
            ("http.request.headers", "arrayValue"),
        ),
    )
    assert checkout.duration_ns == 250_000_000


def test_fixture_mixes_string_and_integer_timestamps() -> None:
    spans = {
        span.span_id: span for span in _parsed(_fixture_bytes("export_two_services.json")).spans
    }
    authorize = spans["a1b2c3d4e5f60718"]

    assert authorize.start_ns == 1_700_000_000_010_000_000
    assert authorize.duration_ns == 80_000_000


def test_fixture_uppercase_ids_are_normalised_to_lowercase() -> None:
    spans = _parsed(_fixture_bytes("export_two_services.json")).spans
    charge = next(span for span in spans if span.name == "POST /charge")

    assert charge.trace_id == TRACE_ID
    assert charge.parent_span_id == "a1b2c3d4e5f60718"
    assert charge.status_message == "card declined"
    assert charge.status_code == 2


def test_bad_spans_fixture_counts_each_rejected_span() -> None:
    result = _parsed(_fixture_bytes("export_bad_spans.json"))

    assert result.rejected == 10
    assert len(result.errors) == 10
    assert len(result.spans) == 2
    assert [span.span_id for span in result.spans] == ["00f067aa0ba902b7", "1111111111111111"]
    assert all(error.startswith("resourceSpans[0].scopeSpans[0].spans[") for error in result.errors)


def test_bad_spans_fixture_keeps_null_parent_and_status_message() -> None:
    result = _parsed(_fixture_bytes("export_bad_spans.json"))
    cart = next(span for span in result.spans if span.name == "POST /cart")

    assert cart.parent_span_id is None
    assert cart.status_code == 2
    assert cart.status_message == "out of stock"
    assert cart.service == "catalog"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("traceId", "0" * 32),
        ("traceId", "a" * 31),
        ("traceId", "a" * 33),
        ("traceId", "g" * 32),
        ("traceId", "0x" + "a" * 30),
        ("traceId", 1234),
        ("traceId", _DELETE),
        ("spanId", "0" * 16),
        ("spanId", "a" * 15),
        ("spanId", "z" * 16),
        ("spanId", None),
        ("parentSpanId", "a" * 15),
        ("parentSpanId", "q" * 16),
        ("parentSpanId", 7),
        ("name", 5),
        ("kind", 6),
        ("kind", -1),
        ("kind", "SPAN_KIND_SERVER"),
        ("kind", True),
        ("kind", 1.0),
        ("startTimeUnixNano", "0"),
        ("startTimeUnixNano", 0),
        ("startTimeUnixNano", "-5"),
        ("startTimeUnixNano", "12a"),
        ("startTimeUnixNano", ""),
        ("startTimeUnixNano", " 1000"),
        ("startTimeUnixNano", "+1000"),
        ("startTimeUnixNano", "9223372036854775808"),
        ("startTimeUnixNano", 2**63),
        ("startTimeUnixNano", 1.5e9),
        ("startTimeUnixNano", True),
        ("startTimeUnixNano", _DELETE),
        ("endTimeUnixNano", "999"),
        ("endTimeUnixNano", "9999999999999999999"),
        ("endTimeUnixNano", 2**63),
        ("endTimeUnixNano", _DELETE),
        ("attributes", "not-a-list"),
        ("attributes", [1]),
        ("attributes", [{"value": {"stringValue": "x"}}]),
        ("attributes", [{"key": "", "value": {"stringValue": "x"}}]),
        ("attributes", [{"key": 3, "value": {"stringValue": "x"}}]),
        ("attributes", [{"key": "k"}]),
        ("attributes", [{"key": "k", "value": "x"}]),
        ("attributes", [{"key": "k", "value": {"stringValue": 5}}]),
        ("attributes", [{"key": "k", "value": {"intValue": "abc"}}]),
        ("attributes", [{"key": "k", "value": {"intValue": 2**63}}]),
        ("attributes", [{"key": "k", "value": {"intValue": "9223372036854775808"}}]),
        ("attributes", [{"key": "k", "value": {"intValue": 1.5}}]),
        ("attributes", [{"key": "k", "value": {"doubleValue": "1.5"}}]),
        ("attributes", [{"key": "k", "value": {"doubleValue": True}}]),
        ("attributes", [{"key": "k", "value": {"doubleValue": 10**400}}]),
        ("attributes", [{"key": "k", "value": {"boolValue": "true"}}]),
        ("status", "ok"),
        ("status", {"code": 3}),
        ("status", {"code": -1}),
        ("status", {"code": "1"}),
        ("status", {"code": 1, "message": 5}),
    ],
)
def test_invalid_span_field_rejects_only_that_span(field: str, value: object) -> None:
    broken = _base_span()
    if value is _DELETE:
        del broken[field]
    else:
        broken[field] = value

    result = _parsed(_request(_base_span(), broken))

    assert result.rejected == 1
    assert len(result.errors) == 1
    assert result.errors[0].startswith("resourceSpans[0].scopeSpans[0].spans[1]: ")
    assert [span.span_id for span in result.spans] == [SPAN_ID]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("parentSpanId", "", None),
        ("parentSpanId", None, None),
        ("parentSpanId", "0" * 16, None),
        ("parentSpanId", "ABCDEF0123456789", "abcdef0123456789"),
        ("kind", 0, 0),
        ("kind", 5, 5),
        ("status", {"code": 2}, 2),
        ("status", None, 0),
        ("name", None, ""),
    ],
)
def test_valid_optional_field_values_are_accepted(
    field: str, value: object, expected: object
) -> None:
    span = _base_span()
    span[field] = value

    parsed = _parsed(_request(span))

    assert parsed.rejected == 0
    assert len(parsed.spans) == 1
    actual = {
        "parentSpanId": parsed.spans[0].parent_span_id,
        "kind": parsed.spans[0].kind,
        "status": parsed.spans[0].status_code,
        "name": parsed.spans[0].name,
    }[field]
    assert actual == expected


@pytest.mark.parametrize(
    ("start", "end"),
    [("1", "1"), ("1", 2), (9_223_372_036_854_775_806, MAX_INT64), (1, "9223372036854775807")],
)
def test_timestamp_boundaries_accepted(start: object, end: object) -> None:
    span = _base_span()
    span["startTimeUnixNano"] = start
    span["endTimeUnixNano"] = end

    assert len(_parsed(_request(span)).spans) == 1


@given(start=st.integers(min_value=-(2**64), max_value=2**64))
def test_start_timestamp_accepted_exactly_when_positive_and_below_2_63(start: int) -> None:
    span = _base_span()
    span["startTimeUnixNano"] = start
    span["endTimeUnixNano"] = MAX_INT64

    result = _parsed(_request(span))

    assert (len(result.spans) == 1) == (0 < start <= MAX_INT64)
    assert result.rejected == 1 - len(result.spans)


@given(value=st.integers(min_value=-(2**64), max_value=2**64))
def test_int_attribute_accepted_exactly_within_int64(value: int) -> None:
    for encoded in (value, str(value)):
        result = _parsed(
            _request(_span_with_attribute({"key": "k", "value": {"intValue": encoded}}))
        )

        assert (len(result.spans) == 1) == (MIN_INT64 <= value <= MAX_INT64)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"stringValue": "hello"}, "hello"),
        ({"stringValue": ""}, ""),
        ({"intValue": "-42"}, -42),
        ({"intValue": 7}, 7),
        ({"intValue": str(MAX_INT64)}, MAX_INT64),
        ({"intValue": str(MIN_INT64)}, MIN_INT64),
        ({"doubleValue": 0}, 0.0),
        ({"doubleValue": 1e-300}, 1e-300),
        ({"boolValue": False}, False),
        ({"boolValue": True}, True),
        ({"arrayValue": {"values": [1]}}, "arrayValue"),
        ({"kvlistValue": {"values": []}}, "kvlistValue"),
        ({"bytesValue": "AAEC"}, "bytesValue"),
        ({}, "empty"),
        ({"stringValue": None}, "empty"),
    ],
)
def test_attribute_value_kinds_are_decoded(value: dict[str, object], expected: object) -> None:
    decoded = _attribute_value(value)

    assert decoded == expected
    assert type(decoded) is type(expected)


def test_absent_service_name_defaults_to_unknown_service() -> None:
    parsed = _parsed(_request(_base_span(), resource_attributes=[]))

    assert [span.service for span in parsed.spans] == [DEFAULT_SERVICE_NAME]


@pytest.mark.parametrize(
    "service_value",
    [
        {"stringValue": ""},
        {"stringValue": 5},
        {"intValue": "5"},
        {"arrayValue": {"values": []}},
        {},
    ],
)
def test_invalid_service_name_rejects_every_span_of_the_resource(
    service_value: dict[str, object],
) -> None:
    attributes = [{"key": "service.name", "value": service_value}]

    result = _parsed(_request(_base_span(), _base_span(), resource_attributes=attributes))

    assert result.spans == []
    assert result.rejected == 2
    assert len(result.errors) == 2


def test_invalid_resource_attribute_rejects_every_span_of_the_resource() -> None:
    attributes = [_service("catalog"), {"key": "", "value": {"stringValue": "x"}}]

    result = _parsed(_request(_base_span(), resource_attributes=attributes))

    assert result.spans == []
    assert result.rejected == 1


def test_resource_attributes_are_prepended_to_span_attributes() -> None:
    span = _base_span()
    span["attributes"] = [{"key": "own", "value": {"boolValue": True}}]
    resource_attributes = [_service("catalog"), {"key": "host", "value": {"stringValue": "h1"}}]

    parsed = _parsed(_request(span, resource_attributes=resource_attributes))

    assert parsed.spans[0].attributes == (
        ("service.name", "catalog"),
        ("host", "h1"),
        ("own", True),
    )


def test_duplicate_span_ids_are_not_deduplicated_by_the_parser() -> None:
    parsed = _parsed(_request(_base_span(), _base_span()))

    assert len(parsed.spans) == 2
    assert parsed.spans[0].span_id == parsed.spans[1].span_id


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b'"text"',
        b"42",
        b"\xff\xfe{}",
        b'{"resourceSpans": 1}',
        b'{"resourceSpans": [1]}',
        b'{"resourceSpans": [{"scopeSpans": {}}]}',
        b'{"resourceSpans": [{"scopeSpans": [1]}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": {}}]}]}',
        b'{"resourceSpans": [{"resource": []}]}',
        b'{"resourceSpans": [{"resource": {"attributes": {}}}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": [NaN]}]}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": [Infinity]}]}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": [-Infinity]}]}]}',
        b"[" * 100_000,
    ],
)
def test_malformed_envelope_is_a_request_error(body: bytes) -> None:
    result = parse_export_request(body)

    assert isinstance(result, RequestError)
    assert result.message


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"resourceSpans": []}',
        b'{"resourceSpans": null}',
        b'{"resourceSpans": [{}]}',
        b'{"resourceSpans": [{"resource": null, "scopeSpans": null}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": []}]}]}',
    ],
)
def test_empty_envelopes_are_valid(body: bytes) -> None:
    parsed = _parsed(body)

    assert parsed.spans == []
    assert parsed.rejected == 0
    assert parsed.errors == []


def test_non_object_span_entries_are_rejected_individually() -> None:
    parsed = _parsed(_request(1, "span", None, _base_span()))

    assert parsed.rejected == 3
    assert len(parsed.spans) == 1
    assert parsed.errors[0].endswith("spans[0]: span must be a JSON object")


_JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20)
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=12), children, max_size=4)
    ),
    max_leaves=25,
)
_SPAN_FIELDS = [
    "traceId",
    "spanId",
    "parentSpanId",
    "name",
    "kind",
    "startTimeUnixNano",
    "endTimeUnixNano",
    "status",
    "attributes",
]


_GENERATED_DEPTH_LIMIT = MAX_JSON_DEPTH - 8
"""Levels left for generated values once the request envelope around them is counted."""


def _depth(value: object) -> int:
    """Container nesting depth of a generated JSON value; scalars have depth 0."""
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    if isinstance(value, dict):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    return 0


def _assert_span_invariants(span: Span) -> None:
    assert _HEX32.fullmatch(span.trace_id) is not None
    assert span.trace_id.strip("0")
    assert _HEX16.fullmatch(span.span_id) is not None
    assert span.span_id.strip("0")
    assert span.parent_span_id is None or _HEX16.fullmatch(span.parent_span_id) is not None
    assert 0 < span.start_ns <= span.end_ns <= MAX_INT64
    assert 0 <= span.kind <= 5
    assert 0 <= span.status_code <= 2
    assert span.service
    for key, value in span.attributes:
        assert key
        assert isinstance(value, str | int | float | bool)
        if isinstance(value, int) and not isinstance(value, bool):
            assert MIN_INT64 <= value <= MAX_INT64


@given(raw=st.binary(max_size=512))
def test_arbitrary_bytes_never_raise(raw: bytes) -> None:
    assert isinstance(parse_export_request(raw), ParseResult | RequestError)


@given(document=_JSON_VALUES)
def test_arbitrary_json_document_never_raises(document: object) -> None:
    raw = json.dumps(document).encode("utf-8")

    assert isinstance(parse_export_request(raw), ParseResult | RequestError)


@given(field=st.sampled_from(_SPAN_FIELDS), value=_JSON_VALUES, service=_JSON_VALUES)
def test_mutated_span_is_counted_and_valid_spans_keep_invariants(
    field: str, value: object, service: object
) -> None:
    assume(_depth(value) <= _GENERATED_DEPTH_LIMIT and _depth(service) <= _GENERATED_DEPTH_LIMIT)
    mutated = _base_span()
    mutated[field] = value
    attributes = [{"key": "service.name", "value": service}]

    result = _parsed(_request(_base_span(), mutated, resource_attributes=attributes))

    assert len(result.spans) + result.rejected == 2
    assert result.rejected == len(result.errors)
    for span in result.spans:
        _assert_span_invariants(span)


@given(value=_JSON_VALUES)
def test_arbitrary_span_entry_is_rejected_or_valid(value: object) -> None:
    assume(_depth(value) <= _GENERATED_DEPTH_LIMIT)
    result = _parsed(_request(value))

    assert len(result.spans) + result.rejected == 1
    assert result.rejected == len(result.errors)
    for span in result.spans:
        _assert_span_invariants(span)
