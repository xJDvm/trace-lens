"""Tests that text reaching the store is valid UTF-8.

``json.loads`` decodes escapes such as ``"\\ud800"`` into lone surrogates, which Python strings can
hold but SQLite cannot store. Every text field the parser accepts must be encodable as UTF-8.
"""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from tracelens.otlp import ParseResult, parse_export_request

TRACE_ID = "5b8efff798038103d269b633813fc60c"
SPAN_ID = "eee19b7ec3c1b174"

# Text that may contain lone surrogates, which the default strategy never produces.
_ANY_TEXT = st.text(alphabet=st.characters(exclude_categories=()), max_size=256)


def _body(
    *,
    name: str = "op",
    message: str = "",
    attr_key: str = "k",
    attr_value: str = "v",
    service: str = "catalog",
) -> bytes:
    span = {
        "traceId": TRACE_ID,
        "spanId": SPAN_ID,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": "1000",
        "endTimeUnixNano": "2000",
        "attributes": [{"key": attr_key, "value": {"stringValue": attr_value}}],
        "status": {"code": 2, "message": message},
    }
    document = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"spans": [span]}],
            }
        ]
    }
    # ensure_ascii=True keeps lone surrogates as escapes, as a real client could send them.
    return json.dumps(document).encode("utf-8")


def _rejected(raw: bytes) -> ParseResult:
    result = parse_export_request(raw)
    assert isinstance(result, ParseResult), result
    assert result.spans == []
    assert result.rejected == 1
    return result


def test_lone_surrogate_in_span_name_is_rejected() -> None:
    result = _rejected(_body(name="\ud800"))

    assert "valid UTF-8" in result.errors[0]


def test_lone_surrogate_in_status_message_is_rejected() -> None:
    result = _rejected(_body(message="ok \udfff"))

    assert "'message' must be valid UTF-8" in result.errors[0]


def test_lone_surrogate_in_attribute_key_is_rejected() -> None:
    result = _rejected(_body(attr_key="bad\ud834"))

    assert "'key' must be valid UTF-8" in result.errors[0]


def test_lone_surrogate_in_string_attribute_value_is_rejected() -> None:
    result = _rejected(_body(attr_value="\ude00"))

    assert "'stringValue' must be valid UTF-8" in result.errors[0]


def test_lone_surrogate_in_service_name_is_rejected() -> None:
    raw = _body(service="\ud800")
    result = parse_export_request(raw)

    assert isinstance(result, ParseResult)
    assert result.spans == []
    assert result.rejected == 1


def test_paired_surrogates_form_a_valid_character() -> None:
    result = parse_export_request(_body(name="smile 😀"))

    assert isinstance(result, ParseResult)
    assert result.rejected == 0
    assert result.spans[0].name == "smile \U0001f600"


@given(text=_ANY_TEXT)
def test_name_is_accepted_exactly_when_it_encodes_as_utf8(text: str) -> None:
    result = parse_export_request(_body(name=text))

    assert isinstance(result, ParseResult)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        assert result.rejected == 1
    else:
        assert result.rejected == 0
        assert result.spans[0].name == text
