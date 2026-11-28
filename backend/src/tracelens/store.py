"""SQLite persistence for spans and per-trace summaries.

The store holds one connection guarded by a lock, so one instance can be shared by the threads
FastAPI uses for synchronous endpoints. Every value reaches SQL as a bound parameter; the SQL
text is made of fixed fragments only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tracelens.model import AttrValue, Span

_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS spans (
        trace_id TEXT NOT NULL,
        span_id TEXT NOT NULL,
        parent_span_id TEXT,
        service TEXT NOT NULL,
        name TEXT NOT NULL,
        kind INTEGER NOT NULL,
        start_ns INTEGER NOT NULL,
        end_ns INTEGER NOT NULL,
        duration_ns INTEGER NOT NULL,
        status_code INTEGER NOT NULL,
        status_message TEXT NOT NULL,
        attributes_json TEXT NOT NULL,
        PRIMARY KEY (trace_id, span_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS traces (
        trace_id TEXT PRIMARY KEY,
        start_ns INTEGER NOT NULL,
        end_ns INTEGER NOT NULL,
        span_count INTEGER NOT NULL,
        error_count INTEGER NOT NULL,
        root_service TEXT NOT NULL,
        root_name TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS spans_service_start ON spans (service, start_ns)",
    "CREATE INDEX IF NOT EXISTS spans_service_name_duration ON spans (service, name, duration_ns)",
    "CREATE INDEX IF NOT EXISTS traces_start ON traces (start_ns)",
)

_INSERT_SPAN = """
    INSERT OR IGNORE INTO spans (
        trace_id, span_id, parent_span_id, service, name, kind, start_ns, end_ns, duration_ns,
        status_code, status_message, attributes_json
    ) VALUES (
        :trace_id, :span_id, :parent_span_id, :service, :name, :kind, :start_ns, :end_ns,
        :duration_ns, :status_code, :status_message, :attributes_json
    )
"""

# Recomputes the summary of one trace from the spans stored so far. An error is a span with
# OTLP status code 2 (STATUS_CODE_ERROR). The root is the span without a parent with the
# earliest start (ties broken by span id); when there is none, the earliest span is used.
_UPSERT_TRACE = """
    INSERT OR REPLACE INTO traces (
        trace_id, start_ns, end_ns, span_count, error_count, root_service, root_name
    )
    SELECT
        :trace_id,
        MIN(start_ns),
        MAX(end_ns),
        COUNT(*),
        SUM(status_code = 2),
        (SELECT service FROM spans WHERE trace_id = :trace_id
            ORDER BY parent_span_id IS NOT NULL, start_ns, span_id LIMIT 1),
        (SELECT name FROM spans WHERE trace_id = :trace_id
            ORDER BY parent_span_id IS NOT NULL, start_ns, span_id LIMIT 1)
    FROM spans
    WHERE trace_id = :trace_id
"""

_TRACE_COLUMNS = """
    trace_id, start_ns, end_ns, span_count, error_count, root_service, root_name
"""

_SPAN_COLUMNS = """
    trace_id, span_id, parent_span_id, service, name, kind, start_ns, end_ns,
    status_code, status_message, attributes_json
"""


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """Aggregate view of one stored trace.

    ``start_ns`` is the earliest span start and ``end_ns`` the latest span end. ``error_count``
    counts spans whose status code is error. ``root_service`` and ``root_name`` describe the
    root span: the parentless span with the earliest start, or the earliest span when no span
    is parentless.
    """

    trace_id: str
    start_ns: int
    end_ns: int
    span_count: int
    error_count: int
    root_service: str
    root_name: str

    @property
    def duration_ns(self) -> int:
        """Elapsed time from the earliest start to the latest end, in nanoseconds."""
        return self.end_ns - self.start_ns


@dataclass(frozen=True, slots=True)
class ServiceEdge:
    """Calls from one service to another, aggregated over a set of traces.

    ``calls`` counts parent-child span pairs where the caller span belongs to ``caller`` and the
    child span to ``callee``. ``errors`` counts the child spans among them whose status code is
    error.
    """

    caller: str
    callee: str
    calls: int
    errors: int


class Store:
    """Span and trace persistence backed by one SQLite database file.

    Opening a store creates the schema if it is missing and switches the database to write-ahead
    logging. Use ``":memory:"`` for a throwaway database.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        """Open or create the database at ``path`` and ensure the schema exists."""
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(os.fspath(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        for statement in _SCHEMA:
            self._conn.execute(statement)

    def close(self) -> None:
        """Close the underlying connection. The store must not be used afterwards."""
        with self._lock:
            self._conn.close()

    def insert_spans(self, spans: Iterable[Span]) -> int:
        """Store ``spans`` and refresh the summaries of the traces they belong to.

        Spans whose ``(trace_id, span_id)`` is already stored are ignored, so sending the same
        batch twice is harmless. The insert and the summary refresh run in one transaction.

        Returns:
            The number of spans newly stored.

        Raises:
            sqlite3.Error: If the database rejects the batch; nothing from the batch is stored.
        """
        batch = list(spans)
        if not batch:
            return 0
        rows = [_span_row(span) for span in batch]
        touched = sorted({span.trace_id for span in batch})
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                inserted = self._conn.executemany(_INSERT_SPAN, rows).rowcount
                for trace_id in touched:
                    self._conn.execute(_UPSERT_TRACE, {"trace_id": trace_id})
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
        return inserted

    def list_traces(
        self,
        service: str | None,
        min_ns: int | None,
        max_ns: int | None,
        error: bool | None,
        limit: int,
        before: int | None = None,
        before_trace_id: str | None = None,
    ) -> list[TraceSummary]:
        """Return up to ``limit`` trace summaries, newest first, matching every given filter.

        Filters:
            service: Only traces that contain a span of this service.
            min_ns, max_ns: Inclusive bounds on the trace duration in nanoseconds.
            error: ``True`` for traces with at least one error span, ``False`` for traces
                without any, ``None`` for no restriction.

        Pagination is a keyset cursor over ``(start_ns, trace_id)``, descending. Pass the
        ``start_ns`` and ``trace_id`` of the last summary of a page as ``before`` and
        ``before_trace_id`` to get the next page. Given ``before`` alone, only traces that
        start strictly earlier are returned.

        Raises:
            ValueError: If ``limit`` is below 1, or ``before_trace_id`` is given without
                ``before``.
        """
        _check_limit(limit)
        if before_trace_id is not None and before is None:
            raise ValueError("before_trace_id requires before")
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if service is not None:
            clauses.append("trace_id IN (SELECT trace_id FROM spans WHERE service = :service)")
            params["service"] = service
        if min_ns is not None:
            clauses.append("end_ns - start_ns >= :min_ns")
            params["min_ns"] = min_ns
        if max_ns is not None:
            clauses.append("end_ns - start_ns <= :max_ns")
            params["max_ns"] = max_ns
        if error is True:
            clauses.append("error_count > 0")
        elif error is False:
            clauses.append("error_count = 0")
        if before is not None:
            params["before"] = before
            if before_trace_id is None:
                clauses.append("start_ns < :before")
            else:
                clauses.append(
                    "(start_ns < :before OR (start_ns = :before AND trace_id < :before_trace_id))"
                )
                params["before_trace_id"] = before_trace_id
        sql = (
            "SELECT"
            + _TRACE_COLUMNS
            + "FROM traces"
            + _where(clauses)
            + " ORDER BY start_ns DESC, trace_id DESC LIMIT :limit"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_summary_from_row(row) for row in rows]

    def get_trace(self, trace_id: str) -> tuple[TraceSummary, list[Span]] | None:
        """Return the summary and all stored spans of ``trace_id``, or ``None`` if unknown.

        Spans are ordered by start time and span id. Tree assembly is left to the caller.
        """
        with self._lock:
            summary_row = self._conn.execute(
                "SELECT" + _TRACE_COLUMNS + "FROM traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if summary_row is None:
                return None
            span_rows = self._conn.execute(
                "SELECT"
                + _SPAN_COLUMNS
                + "FROM spans WHERE trace_id = ? ORDER BY start_ns, span_id",
                (trace_id,),
            ).fetchall()
        return _summary_from_row(summary_row), [_span_from_row(row) for row in span_rows]

    def services(self) -> list[str]:
        """Return the distinct service names seen in stored spans, sorted."""
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT service FROM spans ORDER BY service")
            return [str(row[0]) for row in rows.fetchall()]

    def latency_samples(self, service: str | None, name: str | None, limit: int) -> list[int]:
        """Return the durations in nanoseconds of the last ``limit`` matching spans.

        ``service`` and ``name`` restrict the spans when given. The result is ordered newest
        span first; the caller sorts it when it needs percentiles.

        Raises:
            ValueError: If ``limit`` is below 1.
        """
        _check_limit(limit)
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if service is not None:
            clauses.append("service = :service")
            params["service"] = service
        if name is not None:
            clauses.append("name = :name")
            params["name"] = name
        sql = (
            "SELECT duration_ns FROM spans"
            + _where(clauses)
            + " ORDER BY start_ns DESC, trace_id DESC, span_id DESC LIMIT :limit"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [int(row[0]) for row in rows]

    def service_edges(self, since_ns: int | None, limit_traces: int) -> list[ServiceEdge]:
        """Return the cross-service call edges of the ``limit_traces`` most recent traces.

        Only traces starting at or after ``since_ns`` are considered when it is given. A call
        is a span whose parent is stored and belongs to another service; calls between spans of
        one service and calls from orphaned spans produce no edge. The result is sorted by
        caller, then callee.

        Raises:
            ValueError: If ``limit_traces`` is below 1.
        """
        _check_limit(limit_traces)
        trace_clauses: list[str] = []
        params: dict[str, Any] = {"limit_traces": limit_traces}
        if since_ns is not None:
            trace_clauses.append("start_ns >= :since_ns")
            params["since_ns"] = since_ns
        sql = (
            "SELECT p.service, c.service, COUNT(*), SUM(c.status_code = 2)"
            " FROM spans AS c JOIN spans AS p"
            " ON c.trace_id = p.trace_id AND c.parent_span_id = p.span_id"
            " WHERE c.service <> p.service AND c.trace_id IN ("
            + "SELECT trace_id FROM traces"
            + _where(trace_clauses)
            + " ORDER BY start_ns DESC, trace_id DESC LIMIT :limit_traces)"
            + " GROUP BY p.service, c.service ORDER BY p.service, c.service"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            ServiceEdge(
                caller=str(caller), callee=str(callee), calls=int(calls), errors=int(errors)
            )
            for caller, callee, calls, errors in rows
        ]


def _check_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be at least 1")


def _where(clauses: list[str]) -> str:
    """Return a WHERE clause joining fixed SQL fragments, or an empty string."""
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def _span_row(span: Span) -> dict[str, Any]:
    attributes = [[key, value] for key, value in span.attributes]
    return {
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "service": span.service,
        "name": span.name,
        "kind": span.kind,
        "start_ns": span.start_ns,
        "end_ns": span.end_ns,
        "duration_ns": span.duration_ns,
        "status_code": span.status_code,
        "status_message": span.status_message,
        "attributes_json": json.dumps(attributes, ensure_ascii=False, separators=(",", ":")),
    }


def _span_from_row(row: tuple[Any, ...]) -> Span:
    (
        trace_id,
        span_id,
        parent_span_id,
        service,
        name,
        kind,
        start_ns,
        end_ns,
        status_code,
        status_message,
        attributes_json,
    ) = row
    attributes: tuple[tuple[str, AttrValue], ...] = tuple(
        (str(key), value) for key, value in json.loads(attributes_json)
    )
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        service=service,
        name=name,
        kind=kind,
        start_ns=start_ns,
        end_ns=end_ns,
        status_code=status_code,
        status_message=status_message,
        attributes=attributes,
    )


def _summary_from_row(row: tuple[Any, ...]) -> TraceSummary:
    trace_id, start_ns, end_ns, span_count, error_count, root_service, root_name = row
    return TraceSummary(
        trace_id=trace_id,
        start_ns=start_ns,
        end_ns=end_ns,
        span_count=span_count,
        error_count=error_count,
        root_service=root_service,
        root_name=root_name,
    )
