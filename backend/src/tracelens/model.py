"""Domain types shared by the ingestion, storage and query layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

AttrValue: TypeAlias = str | int | float | bool
"""A span or resource attribute value after OTLP decoding."""


@dataclass(frozen=True, slots=True)
class Span:
    """One finished span as accepted from an OTLP export.

    ``start_ns`` and ``end_ns`` are Unix epoch nanoseconds. ``attributes`` holds the resource
    attributes followed by the span's own attributes, in request order.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: int
    start_ns: int
    end_ns: int
    status_code: int
    status_message: str
    attributes: tuple[tuple[str, AttrValue], ...]

    @property
    def duration_ns(self) -> int:
        """Elapsed time of the span in nanoseconds."""
        return self.end_ns - self.start_ns
