# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
