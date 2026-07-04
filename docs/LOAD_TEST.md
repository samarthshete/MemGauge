# Load Test — finding and localizing the real bottleneck

> **Goal.** Turn MemGauge's latency story from a single synthetic number into a
> *measured* curve under concurrency, then find, localize, and act on the actual
> bottleneck. This document is the reproducible record.

> **Honesty note on absolute numbers.** These runs were executed on a single
> developer laptop (macOS, Docker Desktop, ~8–10 vCPUs shared with other
> containers). Absolute RPS/latency are **directional**, not datacenter numbers.
> What is robust is the *relative* behavior and where the bottleneck sits — those
> reproduce regardless of host.

## Method

- Driver: `scripts/loadtest.py` (async, `httpx`). Closed-loop — concurrency = number
  of in-flight requests; each level runs for a fixed duration.
- Workload: `GET /v1/memories/search`, **a unique nonce appended to every query**
  so each request is a Redis cache *miss* and actually reaches Postgres. (Reusing
  one query would serve from the Redis cache and hide the backend entirely — see
  "Finding 0".)
- Rate limiting disabled for the test (`RATE_LIMIT_PER_MIN=0`) so the limiter does
  not cap throughput before the real bottleneck appears.
- Reproduce:
  ```bash
  RATE_LIMIT_PER_MIN=0 docker compose up -d --build --wait     # 1 worker, pool 5+10
  make loadtest-sweep                                          # writes scratchpad/loadtest.json
  ```

## Finding 0 — the Redis cache masks the backend

A naive test that repeats one query string hits the Redis cache on every request
(`cache:"hit"`) and reports artificially low latency — it never exercises Postgres.
The driver appends a per-request nonce to force `cache:"miss"`. *Lesson: a load test
that doesn't defeat caching measures the cache, not the system.*

## Finding 1 — the connection pool is **not** the bottleneck (hypothesis falsified)

Initial hypothesis: `app/db/session.py` used SQLAlchemy's default async pool
(`pool_size=5, max_overflow=10` ≈ 15 connections), so p99 should cliff once
concurrency exceeds ~15. I made the pool configurable (`DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`) and compared.

**A — 1 worker, pool 5+10 (before):**

| concurrency | RPS | p50 ms | p95 ms | p99 ms |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 30.8 | 30.2 | 44.7 | 67.1 |
| 5 | 44.6 | 113.7 | 161.1 | 249.8 |
| 15 | 42.8 | 358.4 | 603.7 | 706.9 |
| 50 | 42.2 | 1215.1 | 2138.2 | 2617.1 |
| 100 | 44.9 | 2269.9 | 4576.5 | 6205.7 |
| 200 | 41.8 | 4109.0 | 8442.9 | 8618.9 |

**B — 1 worker, pool 20+40 (4× the connections):**

| concurrency | RPS | p50 ms | p95 ms | p99 ms |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 42.3 | 119.9 | 196.1 | 281.9 |
| 15 | 44.6 | 359.6 | 452.8 | 506.9 |
| 50 | 39.2 | 1201.6 | 2053.3 | 2099.2 |
| 200 | 40.3 | 4392.3 | 9176.2 | 9320.3 |

**Quadrupling the pool changed nothing** — same ~44 RPS ceiling, same linear latency
growth. Throughput plateaus at c≈5, *below* the 15-connection limit, and adding
concurrency only grows the queue. That is the signature of a **serial CPU
bottleneck**, not connection-checkout contention.

## Finding 2 — the bottleneck is API-process CPU; the databases are idle

`docker stats` during a c=50 run:

| container | CPU | note |
| --- | ---: | --- |
| **memgauge-api** | **~834%** | ~8 cores — pegged |
| memgauge-postgres | ~16% | nearly idle |
| memgauge-neo4j | <1% | idle |
| memgauge-redis | ~3% | idle |

The work is in the **API process**, not the data layer. Root cause in code:
`app/memory/mock_backend.py` `search()` fetches candidates by recency
(`order_by(Memory.created_at)`) and then ranks them with **pure-Python cosine
similarity** (`app/memory/retrieval.py::cosine_similarity_01`, a 384-dim loop per
candidate per request). The HNSW index on `embedding` exists but this path never
uses it — vector math runs on the CPU of the web process, not in Postgres.

That is why pool tuning did nothing: requests are not waiting on I/O, they are
burning CPU.

## Finding 3 — scaling workers helps, but sublinearly on one host

Made worker count configurable (`UVICORN_WORKERS`, Dockerfile + compose) and scaled
to 4.

**C — 4 workers, pool 5+10 (after):**

| concurrency | RPS | p50 ms | p95 ms | p99 ms |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 52.6 | 82.5 | 223.7 | 416.7 |
| 15 | 60.0 | 189.8 | 665.7 | 954.4 |
| 20 | 61.2 | 304.3 | 669.9 | 862.2 |
| 50 | 54.1 | 762.6 | 2021.5 | 2512.7 |

Peak throughput rose **~44 → ~60 RPS (+36%)** and p50 at c=15 dropped **358 → 190 ms**
— but far from the 4× a perfectly parallel system would give. Two load clients run
in parallel aggregate to ~65 RPS (43 + 22), i.e. **the same ceiling** — confirming
the limit is server-side, not the client. With 4 workers the API already consumes
~8 host cores, so on this single laptop the workers contend for the same finite
CPU. Note the pool math now matters: 4 workers × (5+10) = 60 connections, which must
stay under Postgres's default `max_connections = 100`.

## Conclusions / what actually fixes it

Ranked by leverage (the pool was the *wrong* lever):

1. **Push vector similarity into Postgres** using pgvector's `<=>` operator + the
   existing HNSW index, so similarity is computed in C next to the data instead of
   in a per-request Python loop. This attacks the actual hot path and offloads the
   pegged API CPU. *(Tracked as ROADMAP R13.)*
2. **Reduce per-request CPU overhead** — vectorize ranking (numpy) and sample OTel
   spans instead of always-on (already wired via `OTEL_EXPORTER_OTLP_ENDPOINT`).
3. **Scale out across nodes**, not up on one box — the work is CPU-parallel across
   processes; horizontal replicas behind a load balancer lift throughput linearly
   until a shared dependency (Postgres connections) becomes the next ceiling, at
   which point **PgBouncer** pooling is the answer.
4. **Connection pool sizing** (now configurable) matters only at step 3, to keep
   `workers × pool` under `max_connections`.

## What this run shipped

- `scripts/loadtest.py` — reproducible async concurrency-sweep harness.
- Configurable DB pool (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`) and
  worker count (`UVICORN_WORKERS`).
- A measured, falsified-hypothesis bottleneck diagnosis localized to API CPU.
- `make loadtest-up` / `make loadtest-sweep` targets.
