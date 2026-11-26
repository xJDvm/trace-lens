# trace-lens — design

## Problem
Distributed systems fail in the gaps between services. Tracing (OpenTelemetry) records every
request as a tree of timed *spans* across services, but the raw data is useless without a
backend that ingests it safely and a UI that turns it into a picture: a waterfall, a service
map, latency percentiles.

trace-lens is a small, self-hosted tracing backend + UI:
- accepts **OTLP/HTTP JSON** (`POST /v1/traces`, the real OpenTelemetry wire format), so any
  OTel SDK/collector can export to it;
- stores spans in SQLite with indexes for the queries the UI needs;
- rebuilds trace trees robustly (out-of-order arrival, missing parents, malicious cycles);
- shows a trace list, a per-trace waterfall and latency percentiles with a histogram.

**What it shows a senior reviewer:** untrusted-input handling at a network boundary (size
limits, strict validation, partial-success semantics), data modelling and indexing, a tree
algorithm proven with property-based tests, and a UI that makes production behaviour visible.

## Scope
**Night 1 (MVP):** ingestion with validation + limits, SQLite store, tree assembly, query API,
seeded demo load generator, React UI (trace list + filters, waterfall + span details, latency
histogram), pytest + hypothesis, vitest, one Playwright e2e, screenshot, CI.

**Later nights:** aggregated flame graph; service map (graph from parent/child edges across
services); own t-digest for streaming percentiles; SLO alerts; gzip with decompression cap;
retention/TTL; Docker compose.

## Layout
```
backend/                 Python 3.11+, uv project (pyproject.toml, uv.lock)
  src/tracelens/
    config.py            Settings from env (HOST=127.0.0.1, PORT=4318, DB_PATH=trace-lens.db, limits)
    otlp.py              parse_export_request(raw: bytes) -> ParseResult  (pure, no I/O)
    model.py             Span, TraceSummary dataclasses (frozen, slots)
    tree.py              build_tree(spans) -> TraceTree  (pure)
    store.py             Store(path): insert_spans, list_traces, get_trace, services, latency_stats
    stats.py             percentiles(sorted_ns, qs) and histogram(values_ns, buckets) (pure)
    api.py               create_app(store) -> FastAPI
    demo.py              seeded load generator: python -m tracelens.demo
    __main__.py          python -m tracelens  -> uvicorn on settings.host/port
  tests/
web/                     React 18 + Vite + TS strict (npm workspace)
  src/api.ts  src/format.ts  src/waterfall.ts (pure layout)  src/components/*  src/App.tsx
e2e/                     Playwright spec(s); playwright.config.ts at repo root
package.json             npm workspaces ["web"]; scripts dev/typecheck/lint/test/e2e
```

## Ingestion (`otlp.py`)
Input: `ExportTraceServiceRequest` JSON — `resourceSpans[].resource.attributes[]`,
`resourceSpans[].scopeSpans[].spans[]`. Per span: `traceId` (32 hex, not all zero),
`spanId` (16 hex, not all zero), `parentSpanId` (16 hex or empty/absent), `name`, `kind`
(int 0–5), `startTimeUnixNano`/`endTimeUnixNano` (decimal string **or** int, per the OTLP
JSON mapping; must parse to 0 < start ≤ end < 2^63), `attributes[]` (`{key, value:{stringValue|intValue|doubleValue|boolValue}}`;
other value kinds are stringified to a short type tag), `status.code` (0 unset, 1 ok, 2 error),
`status.message`. Service name = resource attribute `service.name` (default `unknown_service`).

Limits (config constants, tested at boundary):
| Limit | Value |
|---|---|
| Request body | 4 MiB (enforced while streaming the body, not just via Content-Length) |
| Spans per request | 10 000 |
| Span name / service name | 256 chars |
| Attributes per span (incl. resource) | 64; key ≤ 128 chars; string value ≤ 4 096 chars |
| Status message | 1 024 chars |
| JSON nesting | rejected beyond depth 32 (pre-scan before `json.loads`) |

Semantics: malformed JSON / wrong top-level shape → `400`. Valid envelope with some bad spans →
`200` with OTLP partial success `{"partialSuccess":{"rejectedSpans":N,"errorMessage":"..."}}`,
good spans stored. `Content-Type` must be `application/json` (else `415`);
`Content-Encoding` other than identity → `415` (gzip is a later night). Protobuf is out of
scope (documented). `parse_export_request` never raises on any input: it returns
`ParseResult(spans: list[Span], rejected: int, errors: list[str])` or a `RequestError`.
Objects are read field by field; unknown fields are ignored.

## Model
`Span(trace_id, span_id, parent_span_id|None, service, name, kind, start_ns, end_ns,
status_code, status_message, attributes: tuple[tuple[str, AttrValue], ...])`;
`duration_ns = end_ns - start_ns`.

## Storage (`store.py`, stdlib `sqlite3`)
WAL, `busy_timeout=5000`, one connection guarded by a lock (FastAPI sync endpoints run in a
threadpool). Tables:
- `spans(trace_id, span_id, parent_span_id, service, name, kind, start_ns, end_ns, duration_ns,
  status_code, status_message, attributes_json)`, PK `(trace_id, span_id)`, inserted with
  `INSERT OR IGNORE` → re-sending a batch is idempotent.
- `traces(trace_id PK, start_ns, end_ns, span_count, error_count, root_service, root_name)` —
  recomputed for touched trace ids in the same transaction (root = span without parent, earliest
  start; if none, earliest span).
- Indexes: `spans(service, start_ns)`, `spans(service, name, duration_ns)`, `traces(start_ns)`.
All SQL uses bound parameters only.

## Tree assembly (`tree.py`)
`build_tree(spans) -> TraceTree(rows: list[Row], orphans: int, cycles_broken: int)` where
`Row(span, depth, offset_ns)` in waterfall order: DFS, children sorted by `(start_ns, span_id)`.
Rules: a span whose parent is missing is a root (counted as orphan); duplicate span ids keep
the first; parent cycles are detected and broken by treating the earliest-starting member as a
root. Iterative (no recursion) so 10 000-deep chains work.
**Invariants (hypothesis):** every input span id appears exactly once; a parent row precedes
its children; `depth(child) = depth(parent)+1`; roots have depth 0; output independent of
input order; never raises.

## API (`api.py`)
- `POST /v1/traces` — ingestion as above.
- `GET /api/services` → `["api", "auth", ...]`.
- `GET /api/traces?service=&minMs=&maxMs=&error=true|false&limit=50(≤500)&before=<start_ns>&beforeTraceId=<32 hex>`
  → `{traces: TraceSummary[], nextBefore: "<start_ns>"|null, nextBeforeTraceId: "<32 hex>"|null}`,
  newest first. The cursor is the `(start_ns, trace_id)` pair of the last trace of a page, sent
  back as `before` and `beforeTraceId`; the store orders by that pair, so traces sharing a start
  time are neither lost nor repeated across pages. Both cursor fields are `null` unless the page
  is full. `beforeTraceId` without `before` → `422`. Validated with FastAPI `Query` bounds.
- `GET /api/traces/{trace_id}` (32 hex) → `{summary, rows:[{span…, depth, offsetNs}], orphans}`; 404.
- `GET /api/stats/latency?service=&name=` → `{count, p50, p95, p99, histogram:[{leNs, count}]}`
  over the last 10 000 matching spans (exact nearest-rank percentiles; t-digest later).
- `GET /api/healthz`.
Ids/ns are serialized as strings where they may exceed 2^53. No CORS (UI goes through the Vite
proxy). Bind `127.0.0.1:4318` by default; uvicorn `timeout_keep_alive=5`, `limit_concurrency=64`.

## Demo generator (`demo.py`)
`python -m tracelens.demo --url http://127.0.0.1:4318 --traces 300 --seed 42` (or `--db PATH`
to write directly). `random.Random(seed)`, simulation only. Topology: `web-frontend → api-gateway
→ {auth, catalog → {postgres, redis}, checkout → payments}` with log-normal latencies, a slow
tail on `catalog`, ~3 % errors in `payments`. Same seed → byte-identical OTLP payloads (tested).

## UI (`web/`)
Dark, clean layout. Left: filters (service select, min/max ms, errors only). Main: trace table
(time, root service/op, duration bar scaled to the page max, span count, error badge). Trace
page: header (trace id, total duration, services), **waterfall** (one row per span: indented
name, service color chip, bar positioned by `offsetNs/total`, error spans red), click row →
details panel (attributes, status, timings). Service view: p50/p95/p99 tiles + latency
histogram (SVG). `waterfall.ts` (pure: bar left/width %, service color assignment, tick marks)
is unit-tested with vitest. `data-testid`s on table rows, waterfall rows and details panel.

## Testing
- pytest: otlp (valid fixtures, each limit at N and N+1, partial success, never raises —
  hypothesis on arbitrary JSON values), tree (hypothesis invariants above, cycles, orphans,
  deep chains), store (`:memory:`, idempotent re-ingest, summaries, filters, cursor), stats
  (percentiles vs sorted reference), api (FastAPI `TestClient`: status codes, 413/415/400,
  bounds), demo (determinism).
- vitest: `waterfall.ts`, `format.ts`.
- Playwright e2e: webServer starts backend on a temp DB seeded by `demo --db` and the Vite dev
  server; test opens list, sees ≥1 row, filters by service, opens a trace, sees waterfall rows
  and the details panel. A second spec captures `docs/screenshot.png`.

## Commit plan
See `nightly` handoff (mirrors this list): scaffold → model+otlp → otlp limits → tree → tree
properties → store → stats → api → demo → web scaffold+list → waterfall → stats view → e2e →
README+screenshot → CI → CHANGELOG.

## Security notes and dependencies
- Untrusted network input: streamed body cap, depth pre-scan, field-by-field validation, string
  length caps, bounded query params, parameterized SQL, no `eval`/pickle. No auth in MVP — bind
  localhost, documented (put behind a proxy with auth to expose it).
- RNG only in the demo, seeded.
- Python: `fastapi` (+ `pydantic`, `starlette`), `uvicorn` — the standard ASGI stack;
  dev: `pytest`, `hypothesis`, `httpx` (TestClient), `ruff`, `mypy`, `pip-audit`. All pinned in `uv.lock`.
- Web: `react`, `react-dom`; dev: `vite`, `@vitejs/plugin-react`, `typescript`, `eslint`,
  `typescript-eslint`, `vitest`, `@playwright/test`, `concurrently`. Lockfile committed.
  No charting library: histogram and waterfall are hand-written SVG/CSS.
