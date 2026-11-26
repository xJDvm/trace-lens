"""Tests for the size, depth and field limits enforced during OTLP/HTTP JSON ingestion.

Each limit is checked at its boundary value N (accepted) and N+1 (refused). Span-level
violations reject only that span; envelope-level violations refuse the whole request.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tracelens import config
from tracelens.otlp import ParseResult, RequestError, parse_export_request

TRACE_ID = "5b8efff798038103d269b633813fc60c"
SPAN_ID = "eee19b7ec3c1b174"
SPAN_PATH = "resourceSpans[0].scopeSpans[0].spans[0]"
_PAD_PREFIX = b'{"resourceSpans": [], "pad": "'
_PAD_SUFFIX = b'"}'


def _span(**fields: object) -> dict[str, object]:
    """A span that passes every check; keyword arguments override fields."""
    span: dict[str, object] = {
        "traceId": TRACE_ID,
        "spanId": SPAN_ID,
        "name": "op",
        "kind": 1,
        "startTimeUnixNano": "1000",
        "endTimeUnixNano": "2000",
        "attributes": [],
        "status": {"code": 0},
    }
    span.update(fields)
    return span


def _attr(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def _body(
    *span_groups: list[object],
    resource_attributes: list[object] | None = None,
) -> bytes:
    """An export request with one ``resourceSpans`` entry per span group."""
    if resource_attributes is None:
        resource_attributes = [_attr("service.name", "catalog")]
    resource_spans = [
        {
            "resource": {"attributes": resource_attributes},
            "scopeSpans": [{"spans": spans}],
        }
        for spans in span_groups
    ]
    return json.dumps({"resourceSpans": resource_spans}).encode("utf-8")


def _parsed(raw: bytes) -> ParseResult:
    result = parse_export_request(raw)
    assert isinstance(result, ParseResult), result
    return result


def _refused(raw: bytes) -> RequestError:
    result = parse_export_request(raw)
    assert isinstance(result, RequestError), result
    return result


def _body_of_size(size: int) -> bytes:
    """Valid JSON of exactly ``size`` bytes, padded with a string value."""
    filler = size - len(_PAD_PREFIX) - len(_PAD_SUFFIX)
    return _PAD_PREFIX + b"x" * filler + _PAD_SUFFIX


def _nested_body(depth: int) -> bytes:
    """Valid JSON whose nesting depth is exactly ``depth``; the top-level object counts as one."""
    return b'{"resourceSpans": [], "pad": ' + b"[" * (depth - 1) + b"0" + b"]" * (depth - 1) + b"}"


def _assert_span_rejected(parsed: ParseResult, fragment: str) -> None:
    """The request had a single span, which was refused with a message containing ``fragment``."""
    assert parsed.spans == []
    assert parsed.rejected == 1
    assert len(parsed.errors) == 1
    assert parsed.errors[0].startswith(f"{SPAN_PATH}: ")
    assert fragment in parsed.errors[0]


# Body size -------------------------------------------------------------------------------------


def test_body_at_size_limit_is_accepted() -> None:
    raw = _body_of_size(config.MAX_BODY_BYTES)

    assert len(raw) == config.MAX_BODY_BYTES
    assert _parsed(raw).spans == []


def test_body_one_byte_over_size_limit_is_refused() -> None:
    raw = _body_of_size(config.MAX_BODY_BYTES + 1)

    assert "exceeds" in _refused(raw).message


def test_size_is_checked_before_decoding() -> None:
    raw = b"\xff" * (config.MAX_BODY_BYTES + 1)

    assert "exceeds" in _refused(raw).message


# JSON nesting depth ----------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [1, 2, 31, config.MAX_JSON_DEPTH])
def test_nesting_at_depth_limit_is_accepted(depth: int) -> None:
    assert _parsed(_nested_body(depth)).rejected == 0


@pytest.mark.parametrize("depth", [config.MAX_JSON_DEPTH + 1, config.MAX_JSON_DEPTH + 2, 1000])
def test_nesting_beyond_depth_limit_is_refused(depth: int) -> None:
    assert "nested deeper" in _refused(_nested_body(depth)).message


@given(depth=st.integers(min_value=1, max_value=80))
def test_depth_limit_is_exact_for_any_depth(depth: int) -> None:
    result = parse_export_request(_nested_body(depth))

    assert isinstance(result, ParseResult) == (depth <= config.MAX_JSON_DEPTH)


def test_depth_is_refused_before_json_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the decoder must not run on a too-deep body")

    monkeypatch.setattr(json, "loads", fail)

    assert "nested deeper" in _refused(_nested_body(config.MAX_JSON_DEPTH + 1)).message


def test_brackets_inside_strings_do_not_count_towards_depth() -> None:
    value = "[" * 500 + "]" * 500
    raw = json.dumps({"resourceSpans": [], "pad": value}).encode("utf-8")

    assert _parsed(raw).rejected == 0


def test_escaped_quotes_and_backslashes_inside_strings_are_skipped() -> None:
    value = '"' + "[" * 100 + "\\" + "{" * 100 + '"'
    raw = json.dumps({"resourceSpans": [], "pad": value}).encode("utf-8")

    assert _parsed(raw).rejected == 0


# Spans per request -----------------------------------------------------------------------------


def test_request_with_spans_at_limit_is_accepted() -> None:
    parsed = _parsed(_body([_span() for _ in range(config.MAX_SPANS_PER_REQUEST)]))

    assert len(parsed.spans) == config.MAX_SPANS_PER_REQUEST
    assert parsed.rejected == 0


def test_request_one_span_over_limit_is_refused() -> None:
    raw = _body([_span() for _ in range(config.MAX_SPANS_PER_REQUEST + 1)])

    assert "more than 10000 spans" in _refused(raw).message


def test_span_limit_counts_spans_across_resource_entries() -> None:
    half = config.MAX_SPANS_PER_REQUEST // 2

    assert len(_parsed(_body([_span()] * half, [_span()] * half)).spans) == 2 * half
    assert "more than" in _refused(_body([_span()] * half, [_span()] * (half + 1))).message


def test_span_limit_counts_invalid_spans_too() -> None:
    raw = _body([_span(kind=9)] * (config.MAX_SPANS_PER_REQUEST + 1))

    assert "more than 10000 spans" in _refused(raw).message


# Span and service name -------------------------------------------------------------------------


@pytest.mark.parametrize(("length", "accepted"), [(256, True), (257, False)])
def test_span_name_limit(length: int, accepted: bool) -> None:
    parsed = _parsed(_body([_span(name="n" * length), _span()]))

    if accepted:
        assert len(parsed.spans) == 2
        assert parsed.rejected == 0
    else:
        assert len(parsed.spans) == 1
        assert parsed.rejected == 1
        assert parsed.errors[0].startswith(f"{SPAN_PATH}: ")
        assert "'name' exceeds 256 characters" in parsed.errors[0]


def test_span_name_limit_counts_characters_not_bytes() -> None:
    assert len(_parsed(_body([_span(name="é" * 256)])).spans) == 1


@pytest.mark.parametrize(("length", "accepted"), [(256, True), (257, False)])
def test_service_name_limit_rejects_every_span_of_the_resource(length: int, accepted: bool) -> None:
    raw = _body(
        [_span(), _span()],
        resource_attributes=[_attr("service.name", "s" * length)],
    )

    parsed = _parsed(raw)

    if accepted:
        assert len(parsed.spans) == 2
        assert parsed.rejected == 0
    else:
        assert parsed.spans == []
        assert parsed.rejected == 2
        assert all("'service.name' exceeds 256 characters" in e for e in parsed.errors)


# Attributes per span --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra_resource", "own", "accepted"),
    [(0, 63, True), (0, 64, False), (2, 61, True), (2, 62, False)],
)
def test_attribute_limit_counts_resource_attributes(
    extra_resource: int, own: int, accepted: bool
) -> None:
    """Service name plus ``extra_resource`` resource attributes are added to each span."""
    resource = [_attr("service.name", "catalog")]
    resource += [_attr(f"host.{index}", "h") for index in range(extra_resource)]
    span = _span(attributes=[_attr(f"own.{index}", "v") for index in range(own)])

    parsed = _parsed(_body([span], resource_attributes=resource))

    if accepted:
        assert len(parsed.spans) == 1
        assert len(parsed.spans[0].attributes) == 1 + extra_resource + own
    else:
        assert parsed.spans == []
        assert "more than 64 attributes" in parsed.errors[0]


def test_attribute_limit_rejects_only_the_span_that_exceeds_it() -> None:
    too_many = _span(attributes=[_attr(f"k{index}", "v") for index in range(64)])

    parsed = _parsed(_body([too_many, _span()]))

    assert [span.span_id for span in parsed.spans] == [SPAN_ID]
    assert parsed.errors[0].startswith("resourceSpans[0].scopeSpans[0].spans[0]: ")


# Attribute keys and values ---------------------------------------------------------------------


@pytest.mark.parametrize(("length", "accepted"), [(128, True), (129, False)])
def test_attribute_key_limit(length: int, accepted: bool) -> None:
    parsed = _parsed(_body([_span(attributes=[_attr("k" * length, "v")])]))

    if accepted:
        assert len(parsed.spans) == 1
    else:
        _assert_span_rejected(parsed, "attribute 'key' exceeds 128 characters")


@pytest.mark.parametrize(("length", "accepted"), [(4_096, True), (4_097, False)])
def test_attribute_string_value_limit(length: int, accepted: bool) -> None:
    parsed = _parsed(_body([_span(attributes=[_attr("k", "v" * length)])]))

    if accepted:
        assert len(parsed.spans) == 1
    else:
        _assert_span_rejected(parsed, "'stringValue' exceeds 4096 characters")


@pytest.mark.parametrize(("length", "accepted"), [(128, True), (129, False)])
def test_resource_attribute_key_limit_rejects_every_span(length: int, accepted: bool) -> None:
    raw = _body(
        [_span()], resource_attributes=[_attr("service.name", "c"), _attr("k" * length, "v")]
    )

    parsed = _parsed(raw)

    assert len(parsed.spans) == (1 if accepted else 0)
    assert parsed.rejected == (0 if accepted else 1)


@pytest.mark.parametrize(("length", "accepted"), [(4_096, True), (4_097, False)])
def test_resource_attribute_string_value_limit_rejects_every_span(
    length: int, accepted: bool
) -> None:
    raw = _body(
        [_span()],
        resource_attributes=[_attr("service.name", "catalog"), _attr("host", "v" * length)],
    )

    parsed = _parsed(raw)

    if accepted:
        assert len(parsed.spans) == 1
    else:
        assert parsed.spans == []
        assert parsed.rejected == 1


# Status message --------------------------------------------------------------------------------


@pytest.mark.parametrize(("length", "accepted"), [(1_024, True), (1_025, False)])
def test_status_message_limit(length: int, accepted: bool) -> None:
    parsed = _parsed(_body([_span(status={"code": 2, "message": "m" * length})]))

    if accepted:
        assert parsed.spans[0].status_message == "m" * length
    else:
        _assert_span_rejected(parsed, "'message' exceeds 1024 characters")


# Partial success -------------------------------------------------------------------------------


def test_valid_spans_are_kept_when_another_span_breaks_a_limit() -> None:
    parsed = _parsed(_body([_span(name="a"), _span(name="b" * 300), _span(name="c")]))

    assert [span.name for span in parsed.spans] == ["a", "c"]
    assert parsed.rejected == 1
    assert parsed.errors[0].startswith("resourceSpans[0].scopeSpans[0].spans[1]: ")


# Fuzzing ---------------------------------------------------------------------------------------

_NESTED_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=6), children, max_size=3)
    ),
    max_leaves=120,
)
_STRUCTURAL_BYTES = st.text(alphabet='[]{}"\\ 0a,:', max_size=400).map(lambda text: text.encode())


@given(value=_NESTED_JSON)
def test_arbitrary_nested_json_in_attribute_never_raises(value: object) -> None:
    raw = _body([_span(attributes=[{"key": "k", "value": value}])])

    assert isinstance(parse_export_request(raw), ParseResult | RequestError)


@given(value=_NESTED_JSON)
def test_arbitrary_nested_json_as_whole_body_never_raises(value: object) -> None:
    raw = json.dumps(value).encode("utf-8")

    assert isinstance(parse_export_request(raw), ParseResult | RequestError)


@given(raw=_STRUCTURAL_BYTES)
def test_bracket_and_quote_heavy_bytes_never_raise(raw: bytes) -> None:
    assert isinstance(parse_export_request(raw), ParseResult | RequestError)
