"""Parse OTLP/HTTP JSON trace export requests into :class:`Span` objects.

:func:`parse_export_request` is pure (no I/O) and never raises. A request whose envelope cannot
be interpreted yields a :class:`RequestError`. Individual invalid spans are counted as rejected
and reported, following the OTLP partial-success semantics.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple, NoReturn, TypeGuard

from tracelens.model import AttrValue, Span

DEFAULT_SERVICE_NAME = "unknown_service"

_SERVICE_NAME_KEY = "service.name"
_MIN_INT64 = -(2**63)
_MAX_INT64 = 2**63 - 1
_MAX_SPAN_KIND = 5
_MAX_STATUS_CODE = 2
_HEX_PATTERN = re.compile(r"[0-9a-fA-F]+")
_UNSIGNED_DECIMAL_PATTERN = re.compile(r"[0-9]{1,19}")
_SIGNED_DECIMAL_PATTERN = re.compile(r"-?[0-9]{1,19}")
_SCALAR_KINDS = ("stringValue", "intValue", "doubleValue", "boolValue")
_OPAQUE_KINDS = ("arrayValue", "kvlistValue", "bytesValue")


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of a well-formed export request.

    ``spans`` are the valid spans in request order. ``rejected`` counts the span entries that
    failed validation, and ``errors`` holds one human-readable message per rejected entry.
    """

    spans: list[Span]
    rejected: int
    errors: list[str]


@dataclass(frozen=True, slots=True)
class RequestError:
    """The request envelope is malformed, so no span could be interpreted."""

    message: str


class _ParseError(Exception):
    """Base class for internal validation failures."""


class _EnvelopeError(_ParseError):
    """The request shape is wrong, so the whole request is refused."""


class _FieldError(_ParseError):
    """A span or resource field is invalid, so only the affected spans are rejected."""


class _Attribute(NamedTuple):
    """A decoded attribute together with the OTLP value kind it came from."""

    key: str
    kind: str
    value: AttrValue


@dataclass(frozen=True, slots=True)
class _Resource:
    """Service name and attributes shared by every span of one ``resourceSpans`` entry."""

    service: str
    attributes: tuple[tuple[str, AttrValue], ...]


def parse_export_request(raw: bytes) -> ParseResult | RequestError:
    """Parse an ``ExportTraceServiceRequest`` JSON body.

    Args:
        raw: The request body. It must be UTF-8 encoded JSON.

    Returns:
        A :class:`ParseResult` with the valid spans and the rejected count, or a
        :class:`RequestError` if the body is not JSON or its envelope has the wrong shape.
    """
    try:
        return _parse(raw)
    except _EnvelopeError as exc:
        return RequestError(str(exc))


def _parse(raw: bytes) -> ParseResult:
    document = _as_object(_decode_json(raw), _EnvelopeError, "request body")
    spans: list[Span] = []
    errors: list[str] = []
    for index, resource_spans in enumerate(_array_field(document, "resourceSpans", _EnvelopeError)):
        _parse_resource_spans(resource_spans, f"resourceSpans[{index}]", spans, errors)
    return ParseResult(spans=spans, rejected=len(errors), errors=errors)


def _decode_json(raw: bytes) -> object:
    try:
        document: object = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise _EnvelopeError("request body is not valid JSON") from exc
    return document


def _reject_constant(name: str) -> NoReturn:
    """Refuse ``NaN`` and ``Infinity``, which are not standard JSON."""
    raise ValueError(f"non-standard JSON constant {name}")


def _parse_resource_spans(value: object, where: str, spans: list[Span], errors: list[str]) -> None:
    resource_spans = _as_object(value, _EnvelopeError, where)
    resource_obj = _object_field(resource_spans, "resource", _EnvelopeError)
    attribute_entries = _array_field(resource_obj, "attributes", _EnvelopeError)
    entries = _span_entries(resource_spans, where)
    try:
        resource = _parse_resource(attribute_entries)
    except _FieldError as exc:
        errors.extend(f"{path}: {exc}" for path, _ in entries)
        return
    for path, entry in entries:
        try:
            spans.append(_parse_span(entry, resource))
        except _FieldError as exc:
            errors.append(f"{path}: {exc}")


def _span_entries(resource_spans: dict[str, object], where: str) -> list[tuple[str, object]]:
    """Flatten ``scopeSpans[].spans[]`` into ``(location, raw span)`` pairs."""
    entries: list[tuple[str, object]] = []
    for scope_index, scope in enumerate(_array_field(resource_spans, "scopeSpans", _EnvelopeError)):
        scope_where = f"{where}.scopeSpans[{scope_index}]"
        scope_obj = _as_object(scope, _EnvelopeError, scope_where)
        for span_index, entry in enumerate(_array_field(scope_obj, "spans", _EnvelopeError)):
            entries.append((f"{scope_where}.spans[{span_index}]", entry))
    return entries


def _parse_resource(entries: list[object]) -> _Resource:
    attributes = [_attribute(entry) for entry in entries]
    service = DEFAULT_SERVICE_NAME
    for attribute in attributes:
        if attribute.key == _SERVICE_NAME_KEY:
            if (
                attribute.kind != "stringValue"
                or not isinstance(attribute.value, str)
                or not attribute.value
            ):
                raise _FieldError("attribute 'service.name' must be a non-empty string")
            service = attribute.value
    return _Resource(service=service, attributes=_pairs(attributes))


def _parse_span(entry: object, resource: _Resource) -> Span:
    obj = _as_object(entry, _FieldError, "span")
    trace_id = _hex_id(obj.get("traceId"), 32, "traceId")
    span_id = _hex_id(obj.get("spanId"), 16, "spanId")
    parent_span_id = _parent_span_id(obj.get("parentSpanId"))
    name = _text_field(obj, "name")
    kind = _int_field(obj, "kind")
    if not 0 <= kind <= _MAX_SPAN_KIND:
        raise _FieldError("'kind' must be between 0 and 5")
    start_ns = _nanos_field(obj, "startTimeUnixNano")
    end_ns = _nanos_field(obj, "endTimeUnixNano")
    if start_ns == 0:
        raise _FieldError("'startTimeUnixNano' must be greater than zero")
    if end_ns < start_ns:
        raise _FieldError("'endTimeUnixNano' must not be before 'startTimeUnixNano'")
    status = _object_field(obj, "status", _FieldError)
    status_code = _int_field(status, "code")
    if not 0 <= status_code <= _MAX_STATUS_CODE:
        raise _FieldError("'status.code' must be 0, 1 or 2")
    status_message = _text_field(status, "message")
    own_attributes = _pairs(
        _attribute(entry) for entry in _array_field(obj, "attributes", _FieldError)
    )
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        service=resource.service,
        name=name,
        kind=kind,
        start_ns=start_ns,
        end_ns=end_ns,
        status_code=status_code,
        status_message=status_message,
        attributes=resource.attributes + own_attributes,
    )


def _attribute(entry: object) -> _Attribute:
    obj = _as_object(entry, _FieldError, "attribute")
    key = obj.get("key")
    if not isinstance(key, str) or not key:
        raise _FieldError("attribute 'key' must be a non-empty string")
    value = _as_object(obj.get("value"), _FieldError, "attribute 'value'")
    for kind in _SCALAR_KINDS:
        raw = value.get(kind)
        if raw is not None:
            return _Attribute(key, kind, _scalar_value(kind, raw))
    for kind in _OPAQUE_KINDS:
        if value.get(kind) is not None:
            return _Attribute(key, kind, kind)
    return _Attribute(key, "empty", "empty")


def _scalar_value(kind: str, raw: object) -> AttrValue:
    if kind == "stringValue" and isinstance(raw, str):
        return raw
    if kind == "boolValue" and isinstance(raw, bool):
        return raw
    if kind == "intValue":
        return _int64_value(raw)
    if kind == "doubleValue":
        return _double_value(raw)
    raise _FieldError(f"attribute value '{kind}' is invalid")


def _int64_value(raw: object) -> int:
    if _is_int(raw):
        number = raw
    elif isinstance(raw, str) and _SIGNED_DECIMAL_PATTERN.fullmatch(raw) is not None:
        number = int(raw)
    else:
        raise _FieldError("attribute value 'intValue' must be an integer or decimal string")
    if not _MIN_INT64 <= number <= _MAX_INT64:
        raise _FieldError("attribute value 'intValue' is outside the int64 range")
    return number


def _double_value(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise _FieldError("attribute value 'doubleValue' must be a number")
    try:
        number = float(raw)
    except OverflowError:
        # A huge integer cannot be represented as a float; treat it as non-finite.
        number = math.inf
    if not math.isfinite(number):
        raise _FieldError("attribute value 'doubleValue' must be finite")
    return number


def _hex_id(value: object, digits: int, key: str) -> str:
    """Return a lowercase hex id of ``digits`` characters that is not all zeros."""
    text = _hex_text(value, digits, key)
    if not text.strip("0"):
        raise _FieldError(f"'{key}' must not be all zeros")
    return text


def _hex_text(value: object, digits: int, key: str) -> str:
    if not isinstance(value, str) or len(value) != digits or _HEX_PATTERN.fullmatch(value) is None:
        raise _FieldError(f"'{key}' must be {digits} hex characters")
    return value.lower()


def _parent_span_id(value: object) -> str | None:
    """Parent id, where absent, empty or all zeros all mean the span has no parent."""
    if value is None or value == "":
        return None
    text = _hex_text(value, 16, "parentSpanId")
    return None if not text.strip("0") else text


def _nanos_field(obj: dict[str, object], key: str) -> int:
    value = obj.get(key)
    if _is_int(value):
        nanos = value
    elif isinstance(value, str) and _UNSIGNED_DECIMAL_PATTERN.fullmatch(value) is not None:
        nanos = int(value)
    else:
        raise _FieldError(f"'{key}' must be a decimal string or integer")
    if not 0 <= nanos <= _MAX_INT64:
        raise _FieldError(f"'{key}' must be a timestamp in [0, 2^63)")
    return nanos


def _int_field(obj: dict[str, object], key: str) -> int:
    """Integer field; an absent or null field takes the protobuf default of 0."""
    value = obj.get(key)
    if value is None:
        return 0
    if not _is_int(value):
        raise _FieldError(f"'{key}' must be an integer")
    return value


def _text_field(obj: dict[str, object], key: str) -> str:
    """String field; an absent or null field takes the protobuf default of ``""``."""
    value = obj.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _FieldError(f"'{key}' must be a string")
    return value


def _pairs(attributes: Iterable[_Attribute]) -> tuple[tuple[str, AttrValue], ...]:
    return tuple((attribute.key, attribute.value) for attribute in attributes)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_object(value: object, error: type[_ParseError], what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise error(f"{what} must be a JSON object")
    return value


def _object_field(obj: dict[str, object], key: str, error: type[_ParseError]) -> dict[str, object]:
    """Object field; an absent or null field is treated as an empty object."""
    value = obj.get(key)
    if value is None:
        return {}
    return _as_object(value, error, f"'{key}'")


def _array_field(obj: dict[str, object], key: str, error: type[_ParseError]) -> list[object]:
    """Array field; an absent or null field is treated as an empty array."""
    value = obj.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise error(f"'{key}' must be an array")
    return value
