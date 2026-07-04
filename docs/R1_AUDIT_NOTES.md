# R1 Audit Notes

> Scope: **R1 only** — take MemGauge from "Unverified" to "end-to-end runnable" on a Python 3.11 + Docker host. No features, no redesign.
> Companion runbook: [R1_RUNBOOK.md](R1_RUNBOOK.md). Project state: [../STATUS.md](../STATUS.md).

**Last updated:** 2026-06-21 (prepared in an audit sandbox with **no Docker** and **Python 3.10**; the live run is executed by the developer on a Docker + 3.11 host — see runbook).

## Services discovered (`docker-compose.yml`)

| Service | Image | Container port | Host port | Health |
| --- | --- | --- | --- | --- |
| `api` | built from `Dockerfile` (`python:3.11-slim`, uvicorn) | 8000 | **18000** | `/healthz` 200 (green only when PG+Neo4j+Redis up) |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | **15432** | `pg_isready` |
| `neo4j` | `neo4j:5-community` | 7687 (bolt), 7474 (http) | **17687**, **17474** | `cypher-shell RETURN 1` |
| `redis` | `redis:7` | 6379 | **16379** | `redis-cli ping` |
| `prometheus` | `prom/prometheus:v2.55.1` | 9090 | **19090** | `/-/healthy` |
| `grafana` | `grafana/grafana:11.4.0` | 3000 | **13000** | `/api/health` |

Startup ordering is correct: `api` waits on PG/Neo4j/Redis `service_healthy`; `prometheus` waits on `api` healthy; `grafana` waits on `prometheus` healthy.

## Expected ports (host)

API `18000` · Postgres `15432` · Neo4j bolt `17687` / http `17474` · Redis `16379` · Prometheus `19090` · Grafana `13000`. All bound to `127.0.0.1` (local-only).

## Env vars required

From `.env.example` (all have safe defaults in `app/config.py`; **all local-only / non-secret**):

- `MEMGAUGE_BACKEND=mock` (default; the only secret-free backend — keep it)
- `MEMGAUGE_API_TOKEN=dev-token` (now enforced on mutating/expensive routes; local demo default only)
- `POSTGRES_DSN`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `REDIS_URL` (service DSNs)
- `OTEL_EXPORTER_OTLP_ENDPOINT=` (empty → spans go to console)
- `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` (fastembed; falls back to deterministic hash offline)
- `CORS_ALLOW_ORIGINS=`, `RATE_LIMIT_PER_MIN=60` (now enforced by CORS middleware and the fixed-window rate limiter)

The compose file supplies these via `${VAR:-default}`, so `docker compose up` works **with no `.env`**. A `.env` is only needed for the **host-side** `make seed`/`make eval` step (the Makefile injects host-port DSNs itself, but a `.env` documents intent).

## How the pieces fit (run path)

1. **Schema:** `app/db/init.sql` is mounted into Postgres at `/docker-entrypoint-initdb.d/001-init.sql`. **It runs only once, on a fresh `postgres-data` volume.** Nothing in the app calls `create_all()` — so a stale volume = no schema = eval failure. (See Blocker 3.)
2. **App:** `Dockerfile` runs `uvicorn app.main:app`. Requires Python 3.11 (code uses `datetime.UTC`). Container base is already `python:3.11-slim` — good.
3. **Seed/eval:** `make seed` / `make eval` run **on the host** against the mapped ports (`127.0.0.1:15432/17687/16379`) using `.venv/bin/python`. They do **not** run inside the api container.
4. **Markdown gate report:** `scripts/run_eval_ci.py` writes `report.md` (PASS/FAIL + metrics table) and exits non-zero on regression.
5. **HTML report:** server-rendered at `GET /report/{run_id}` (Jinja2 `app/templates/report.html`). The `run_id` comes from the eval run (printed by the runner / in the `eval_runs` table / from `POST /v1/eval/run`).

## Current blockers (ranked)

| # | Blocker | Impact on R1 | Fix (minimal, in-scope) |
| --- | --- | --- | --- |
| **B1** | **No host env bootstrap.** `make seed`/`make eval` hardcode `.venv/bin/python`, but nothing creates `.venv` or installs deps, and README never says to. A fresh dev cannot run the eval. | Breaks "fresh developer can reproduce" + "eval runs end-to-end". | Add `make venv` target (`python3.11 -m venv .venv && pip install -e ".[dev]"`) + document. No new deps. |
| **B2** | **No documented eval → HTML-report path.** `make eval` only writes markdown; the HTML report needs the app + a `run_id`. | Breaks "HTML report generated/served". | Add `make report` helper that runs eval via the API (`POST /v1/eval/run`), captures `run_id`, and prints the `/report/{run_id}` URL. Server-rendered, no UI changes. |
| **B3** | **Schema only applies on a fresh PG volume.** Re-running on a stale `postgres-data` volume skips `init.sql`. | Intermittent "schema setup" failure for repeat runs. | Document `docker compose down -v` reset; add `make reset`. Optionally apply `init.sql` idempotently in the R1 target (it already uses `CREATE TABLE IF NOT EXISTS`). |
| **B4** | **No single canonical startup command.** Steps scattered across README/DEMO. | Friction for "documented command sequence". | Add one `make r1` target chaining the whole flow; document in runbook. |
| B5 | Host-side seed/eval needs the 3 services reachable on mapped ports **before** running. No wait/guard on the host side. | Race: eval run before stack healthy → connection error. | `make r1` uses `docker compose up -d --wait` (blocks until healthchecks pass) before host steps. |

## Risky assumptions

- The developer's host has **Python 3.11** specifically (not just any python3). The Makefile's `PYTHON ?= .venv/bin/python` assumes the venv was built with 3.11. Documented explicitly in the runbook.
- `fastembed` model download (`BAAI/bge-small-en-v1.5`) may be slow/blocked on first run; the deterministic hash fallback covers offline, and CI forces `EMBEDDING_MODEL=__offline-*-model__`. R1 runbook recommends the offline model for a fast, deterministic first run.
- Compose image pulls require network on first `up`.

## Commands attempted (in this audit sandbox)

- `which docker` → **not found**; `/var/run/docker.sock` → **absent**. Docker cannot run here.
- `python3 --version` → **3.10.12**; project requires `>=3.11,<3.12`. `datetime.UTC` imports fail on host → `mock_backend`, `mem0_backend`, `runner` cannot import here.
- Installed core deps ad-hoc and ran the 3.11-independent unit subset: `pytest tests/test_scoring.py tests/test_retrieval.py tests/test_embeddings.py` → **10 passed**.
- Replicated pure helpers to verify `extract_fact`, `is_sarcastic`, `classify_case`, and `rank_memories` signal breakdown → all correct.

## Failures observed

- Full `make test-unit` / any module importing `datetime.UTC` → `ImportError` on Python 3.10 (expected; confirms the 3.11 pin is real and load-bearing).
- No live stack could be started in that sandbox → DB-backed flows were **Unverified until the host run**. Superseded by the 2026-06-29 host verification recorded in `STATUS.md` and `docs/R1_RUNBOOK.md`.

## Fixes made (this R1 pass — config/docs/startup only, no app logic)

1. `.env.example` — added a header comment clarifying all values are **local-only, non-secret**, and that `.env` must never be committed (it already is gitignored). No secret values.
2. `Makefile` — added `venv`, `report`, `reset`, `r1`, and `smoke` targets (no changes to existing targets; existing `eval` still works).
3. `scripts/r1_smoke.py` — minimal end-to-end smoke check (services reachable, eval ran, HTML report contains expected markers). No product behavior.
4. `docs/R1_RUNBOOK.md` — exact, copy-paste reproduction steps with an evidence table for the developer to fill in.

**Not changed in R1:** no application code, no dependencies, no database choices, no auth, no frontend, no extra metrics. Later passes fixed BUG-1/BUG-2 and completed Phase 7 security; see `STATUS.md` for current reality.
