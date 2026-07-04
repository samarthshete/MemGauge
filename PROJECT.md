# PROJECT.md — MemGauge

> Stable source of truth. What MemGauge is and why. Changes rarely.
> For current state see [STATUS.md](STATUS.md); for what's next see [ROADMAP.md](ROADMAP.md); for how to work here see [AGENTS.md](AGENTS.md).

## One-line pitch

MemGauge is a memory-quality observability and regression-gate service that sits beside an AI-agent memory layer (modeled on Mem0), scores retrieval quality across three failure modes, and fails CI when quality or latency regresses.

## Problem & who it's for

Agent memory layers silently degrade: a retrieval starts missing relevant facts, a superseded fact keeps resurfacing, or a sarcastic/ironic utterance gets stored as a true fact. Teams shipping agents have no objective gate to catch this before it reaches users. MemGauge is for backend/ML engineers who run a memory layer in production and want (a) instrumented `add`/`search` with traces and metrics, and (b) a benchmark + CI gate that blocks regressions.

## Target context (the Mem0 backend role)

MemGauge is built to demonstrate the work a Mem0-style memory backend engineer does: model entities and temporal relationships in a graph database, store embeddings in Postgres/pgvector, run hybrid retrieval, and make the whole thing observable and testable. It deliberately does **not** reimplement Mem0's memory-extraction algorithm. Instead it provides a narrow `MemoryBackend` interface with two implementations: a secret-free deterministic `mock` (default) and an optional real `mem0` adapter that mirrors Mem0's results into the same Postgres tables and Neo4j graph so metrics are computed identically.

## Goal

Run end-to-end via `docker compose up` with **zero external API keys** (default `mock` backend), expose a server-rendered eval report + Grafana, and provide a CI gate (`scripts/run_eval_ci.py`) that exits non-zero on regression.

## Architecture

```
                         ┌──────────────────────────────┐
   client ──HTTP──▶      │  FastAPI app (app/main.py)    │
                         │  middleware: request-id,      │
                         │  OTel span, Prom metrics      │
                         └───────────────┬──────────────┘
        routers: health · memories · eval · report
                                         │
                 ┌───────────────────────┼─────────────────────────┐
                 ▼                       ▼                         ▼
        MemoryBackend (factory)    Eval runner            Observability
        ├─ mock (default)          (app/eval/*)           (OTel → console/OTLP,
        └─ mem0 (optional)          benchmark + metrics    Prometheus registry)
                 │                       │
        ┌────────┴───────────┐           │
        ▼                    ▼           ▼
  Postgres 16 + pgvector   Neo4j 5    eval_runs / eval_case_results (Postgres)
  memories, memory_events  Entity/Memory/User nodes,
  embedding vector(384)    temporal RELATES_TO edges (valid_from/valid_to)
                 │
              Redis 7  (search-result cache, fail-open)

  Prometheus scrapes /metrics ──▶ Grafana dashboard (provisioned)
```

## Data model

**Postgres** (`app/db/init.sql`, `app/db/models.py`):

- `memories` — `id uuid pk`, `user_id`, `agent_id?`, `run_id?`, `content`, `embedding vector(384)`, `is_active bool`, `superseded_by uuid? → memories.id`, `created_at`, `updated_at`. Indexes: btree on `user_id`, **HNSW** on `embedding` (`vector_cosine_ops`), partial index on `is_active`. Soft-delete + supersede chain (no hard deletes in normal flow).
- `memory_events` — audit trail; `event_type ∈ {ADD, UPDATE, DELETE, NOOP}` (CHECK), `memory_id?` (nullable so NOOP has no row), `old_content`, `new_content`.
- `eval_runs` — one row per benchmark run: `recall_at_5`, `precision`, `staleness_rate`, `false_fact_rate`, `p95_search_ms`, `p95_add_ms`, `total_cases`, `passed`, `baseline_id?`, `git_sha?`, `backend_mode`.
- `eval_case_results` — per-case: `failure_mode ∈ {none, retrieval_miss, stale_fact, false_fact}` (CHECK), `expected jsonb`, `retrieved jsonb`, `score`, `latency_ms`.

**Neo4j** (`app/graph/`):

- Nodes: `User {id}`, `Memory {id, content}`, `Entity {name}` (uniqueness constraints on each).
- Edges: `(User)-[:OWNS]->(Memory)`, `(Entity)-[:RELATES_TO {user_id, predicate, object, memory_id, valid_from, valid_to}]->(Entity)`. **Temporal:** active facts have `valid_to IS NULL`; superseding a fact sets `valid_to` rather than deleting the edge.
- Three canonical read queries (`app/graph/queries.py`): multi-hop `RELATED_ENTITIES` (1–2 hops), `ENTITY_RESOLUTION_COLLISIONS` (name-normalization collisions), `ACTIVE_FACTS` (current facts for an entity).

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Liveness + Postgres/Neo4j/Redis dependency status (503 if any down). |
| GET | `/metrics` | Prometheus exposition; refreshes eval gauges from latest run. |
| POST | `/v1/memories` | Add memory; returns memory, events, `stored`, and (if stored) extracted `fact`. Requires bearer token. |
| GET | `/v1/memories/search` | Hybrid search; each item carries `score` + `signals{vector,keyword,graph}`. Redis-cached. |
| GET | `/v1/memories` | List active memories (paginated). |
| DELETE | `/v1/memories/{id}` | Soft-delete; returns audit trail; 404 if not found. Requires bearer token. |
| POST | `/v1/eval/run` | Run benchmark; persists run + case results. Requires bearer token. |
| GET | `/v1/eval/runs` | List eval runs (paginated). |
| GET | `/v1/eval/report/{run_id}` | JSON report for a run (404 if missing). |
| GET | `/report/{run_id}` | Server-rendered HTML report (Jinja2). |

Graph queries are **not** exposed as a public route. They are exercised by the eval runner and integration tests via `Neo4jClient`.

## Scope boundaries

**Build:** instrumented `add`/`search`; Postgres+pgvector embeddings; Neo4j entity/temporal graph; hybrid retrieval with per-signal breakdown; deterministic mock backend; optional real mem0 adapter behind env flag; 3-failure-mode benchmark; CI regression gate; one server-rendered HTML report; Prometheus + Grafana + OTel.

**Never build:** a SPA / heavy JS frontend; user accounts / OAuth / login; multiple interchangeable databases (one Postgres, one Neo4j, one Redis); streaming responses; a reimplementation of Mem0's memory-extraction algorithm; any committed secrets.

## Tech stack

Python 3.11 (strictly `>=3.11,<3.12`; uses `datetime.UTC`). FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, pgvector, neo4j async driver, redis async, fastembed (with deterministic hash fallback), OpenTelemetry (SDK + OTLP exporter), prometheus-client, Jinja2, uvicorn. Postgres 16 (pgvector image), Neo4j 5 community, Redis 7, Prometheus, Grafana. Tooling: ruff, mypy, pytest (+asyncio, +cov). Docker Compose orchestrates everything.

## Key design decisions / ADRs

1. **Pluggable backend + secret-free mock default.** `MEMGAUGE_BACKEND=mock` is the only backend that runs with no API keys, so the repo is runnable and CI is reproducible out of the box. The `mem0ai` package and keys are imported lazily *inside* `mem0_backend.py` runtime paths only, never at import time. Rationale: keep the demo zero-friction and the eval deterministic; prove the architecture without depending on a paid service.
2. **Hybrid retrieval weights `0.6 vector / 0.2 keyword / 0.2 graph`.** Vector dominates (semantic recall), keyword catches exact-token matches the embedding misses, graph gives a bounded boost when an entity in the query has an active fact edge. Each signal is returned per-item so the report can explain *why* something ranked.
3. **Soft-delete + temporal graph (no hard deletes).** Postgres uses `is_active`/`superseded_by`; Neo4j edges carry `valid_from`/`valid_to`. A contradiction produces an `UPDATE` event, deactivates the old row, and closes the old edge — the stale version is excluded from active search but remains auditable. This is what makes "stale fact" a measurable failure mode.
4. **Deterministic offline embeddings.** `EmbeddingProvider` uses fastembed when available and falls back to a stable 384-d blake2b hash vector offline (and in CI via `EMBEDDING_MODEL=__offline-*-model__`), so the benchmark is reproducible without downloading models.
5. **Single shared persistence for both backends.** The mem0 adapter mirrors Mem0's add/search into the *same* Postgres tables and Neo4j graph as the mock, so the eval runner, scoring, and graph queries see both backends through one lens.
