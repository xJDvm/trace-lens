# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-27

### Added

- `GET /api/service-map`: the services and the cross-service calls between them, with call and
  error counts, over the most recent traces. Optional `sinceNs` (digits, nanoseconds) keeps only
  traces that start at or after that time, and `traces` (1 to 1 000, default 500) sets how many
  recent traces are considered. Invalid values are refused with `422`.
- Service map screen at `#/map`: services are placed in a layered layout with their error rate.
  Edges grow thicker with more calls and are red when some call failed. Clicking a service opens
  its latency view.
- Flame graph tab in the trace view, next to the waterfall (Waterfall | Flame graph). Each span is
  one frame placed by its time range and its depth in the span tree; error spans are red.
- Property-based test of the cross-service edge counts against a plain Python reference, and
  end-to-end coverage of the service map and the flame graph.

### Fixed

- Trace list filters are kept when returning from a trace.

## [0.1.0] - 2026-11-25

### Added

- OTLP/HTTP JSON ingestion at `POST /v1/traces` with strict field validation, partial-success
  responses (`rejectedSpans`) and enforced limits: 4 MiB body (checked while streaming),
  10 000 spans per request, 64 attributes per span, string length caps, and a JSON nesting depth
  cap of 32. Protobuf and gzip are not supported yet.
- SQLite store (stdlib `sqlite3`, WAL mode) with idempotent re-ingestion, per-trace summaries and
  indexes for service, span name and time-range queries.
- Trace tree assembly in waterfall order. Orphan spans become roots, duplicate span ids are
  ignored after the first, and parent cycles are broken. Covered by property-based tests.
- Query API: services, trace list with keyset cursor pagination and filters (service, duration,
  errors only), trace detail with span depth and offsets, latency percentiles and histogram,
  and a health endpoint.
- Seeded demo load generator (`python -m tracelens.demo`) that produces a synthetic
  microservice topology with deterministic output for a given seed.
- React web UI: trace list with filters, per-trace waterfall with span details, and per-service
  latency percentiles with a histogram.
- Playwright end-to-end test that browses demo traces in Chromium.
- GitHub Actions CI with backend (Python 3.11 and 3.13), web (Node 22 and 24) and end-to-end jobs.
- MIT license.
