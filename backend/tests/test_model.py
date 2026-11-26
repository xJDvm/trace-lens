"""Tests for the span model."""

from __future__ import annotations

import dataclasses

import pytest

from tracelens.model import Span


def _span(start_ns: int = 100, end_ns: int = 350) -> Span:
    return Span(
        trace_id="0af7651916cd43dd8448eb211c80319c",
        span_id="b7ad6b7169203331",
        parent_span_id=None,
        service="api",
        name="GET /",
        kind=2,
        start_ns=start_ns,
        end_ns=end_ns,
        status_code=0,
        status_message="",
        attributes=(("http.method", "GET"),),
    )


def test_duration_is_end_minus_start() -> None:
    assert _span(start_ns=100, end_ns=350).duration_ns == 250


def test_zero_length_span_has_zero_duration() -> None:
    assert _span(start_ns=42, end_ns=42).duration_ns == 0


def test_span_is_frozen() -> None:
    span = _span()

    with pytest.raises(dataclasses.FrozenInstanceError):
        span.name = "changed"  # type: ignore[misc]


def test_span_uses_slots() -> None:
    assert not hasattr(_span(), "__dict__")
