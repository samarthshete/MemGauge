# STATUS.md — MemGauge

> **Read this first.** Living snapshot of verified reality. Everything here is either verified or explicitly marked `Unverified`. No optimistic guessing.
> Update after **any** change. See [ROADMAP.md](ROADMAP.md) for what's next, [PROJECT.md](PROJECT.md) for the stable spec.

**Last updated:** 2026-07-04T22:00Z

**D1 deploy-preflight status:** ✅ **DONE (2026-07-04)** — the repo is deploy-ready; **the actual deploy has NOT happened** (no cloud resource exists; awaiting explicit approval — see [docs/DEPLOY_PREFLIGHT.md](docs/DEPLOY_PREFLIGHT.md)). All previously dirty/untracked work (R1–R12, security, baseline, docs) is committed in 11 coherent commits and pushed to `origin/main`; `.env` untracked and secret-scan clean; `report.md`/`report.html`/`scratchpad/` gitignored (`report.md` untracked from git). `fly.toml` added (matches DEPLOY.md; corrected to `[[http_service.checks]]`); DEPLOY.md now documents the one-time `psql ... -f app/db/init.sql` step for managed Postgres, that Neo4j constraints are created by the **first eval run** (not app startup), and the full fly-secrets list by name. Preflight verified on the committed code: `make lint` clean, `make test` 33 passed (83.83% coverage), `make r1` → gate PASS + `R1 SMOKE: PASS`, `docker build` clean (168 MB, non-root). Known caveat for the deployed demo: the committed baseline encodes laptop latencies, so cloud eval runs will likely fail the latency gate on `/report/{run_id}` (documented, deliberately not "fixed" in code).

**Overall health:** 🟢 **Green (core verified)** — **R1 is VERIFIED end-to-end on a real host** (macOS, Docker 29.4.3 / Compose v5.1.4, Python 3.11.15), **R11 is DONE**, **R5 security is DONE + verified**, **R6 observability is DONE + verified**, **R7 resilience is DONE + verified**, **R8 is DONE**, **R9 dev environment pinning is DONE + verified**, and **R10 coverage cleanup is DONE + verified**. `data/baseline.json` was regenerated from a clean live run with the behavior-driven classifier, and the CI gate is verified against it (PASS at exit 0; forced regression → FAIL at non-zero, reverted → PASS). The full stack comes up all-healthy, `/healthz` reports all `up`, `/metrics` serves `memgauge_*`, Prometheus scrapes non-zero MemGauge series, Grafana loads the provisioned dashboard, Redis-down search fails open, hard Postgres/Neo4j outage health behavior is verified, optional OTLP collector export is verified, the eval runs end-to-end, `report.html` renders, and `make smoke` prints `R1 SMOKE: PASS`. `make doctor`, `make test-unit`, `ruff`, `mypy`, full `make test`, `make r6-observability`, `make r7-resilience`, `make hard-dependencies`, `make otlp-config-check`, and `make otlp-live-check` pass on this host. Optional real `mem0` remains externally gated by local `mem0ai` + API keys; the no-secret preflight now fails cleanly and intentionally when those are absent.

**R1 status:** ✅ **VERIFIED (2026-06-29)** — `make venv && make r1` ran green; every acceptance check passed and the [docs/R1_RUNBOOK.md](docs/R1_RUNBOOK.md) evidence table is filled. No code fixes were needed (Docker daemon just had to be started).

**R11 status:** ✅ **DONE (2026-06-29)** — baseline regenerated on this host via `run_eval_ci.py --dataset all --set-baseline` (the supported flag) on a fresh `make reset && make stack-up` stack. **Before → after:** `staleness_rate` **0.125 → 0.000** (the 0.125 was the pre-R4 label artifact), `false_fact_rate` **0.125 → 0.125** (genuinely behavior-driven — the mock backend retrieves 5 facts flagged sarcastic; not a label artifact), `p95_search_ms` 42.95 → 9.48, `p95_add_ms` 105.37 → 50.77, `recall_at_5` 0.875 (unchanged), `precision` 0.500 (unchanged). `failure_mode_counts` went from `{false_fact:5, none:27, retrieval_miss:3, stale_fact:5}` → `{false_fact:5, none:35}`. Gate re-run against the fresh baseline: **PASS, exit 0**. No application logic was changed — the baseline conforms to the code.

**R5 status:** ✅ **DONE (2026-06-29)** — Phase 7 security is implemented and verified. Mutating/expensive routes (`POST /v1/memories`, `DELETE /v1/memories/{id}`, `POST /v1/eval/run`) require `Authorization: Bearer <MEMGAUGE_API_TOKEN>` and return 401 without it; reads, health, metrics, and reports remain public by policy. Redis-backed fixed-window rate limiting is wired with in-memory fallback and fail-open behavior; CORS honors `CORS_ALLOW_ORIGINS`. Unit tests cover token rejection/acceptance, 429 over limit, Redis-down fallback, fail-open, and CORS. Integration tests cover protected-route 401/200 behavior against real Postgres/Neo4j/Redis.

**R6 status:** ✅ **DONE (2026-06-29)** — Observability proof is repeatable via `make r6-observability`. The verifier performs a protected memory add and public search, confirms direct `/metrics` add/search counts are non-zero, waits for Prometheus to scrape those series, loads Grafana health + the provisioned `MemGauge Overview` dashboard, and checks API container logs for both a console-exported `memory.add` span and structured `trace_id`. Evidence is recorded in [docs/R6_OBSERVABILITY_RUNBOOK.md](docs/R6_OBSERVABILITY_RUNBOOK.md).

**R7 status:** ✅ **DONE (2026-06-29)** — Resilience proof is repeatable via `make r7-resilience`. The verifier confirms bad memory input returns 422, deleting a missing memory returns 404, Redis-down health returns 503/degraded, search still returns the seeded memory while Redis is stopped, and Redis restarts cleanly with `/healthz` back to all up. Evidence is recorded in [docs/R7_RESILIENCE_RUNBOOK.md](docs/R7_RESILIENCE_RUNBOOK.md).

**R8 status:** ✅ **DONE (2026-06-29)** — Removed the dead `app/routers/graph.py` file from the working tree and updated docs to state the intended design: graph queries are internal via `Neo4jClient`, not public HTTP routes. Verified with `rg` that no code imports the deleted router and stale docs are gone.

**R9 status:** ✅ **DONE (2026-06-29)** — Dev environment is pinned and self-checking. Added `.python-version` and `.tool-versions` pinning Python `3.11.15`, added [docs/DEV_ENV.md](docs/DEV_ENV.md), and added `make doctor` via `scripts/dev_doctor.py`. Verified `make doctor` on this host: Python 3.11.15, version files, FastAPI/Pytest imports, Docker 29.4.3, Docker Compose v5.1.4, Docker daemon, and compose config all pass.

**R10 status:** ✅ **DONE (2026-06-29)** — Coverage gates are verified and the local coverage artifact is pruned. `make test-unit` passed at 97.59% scoped coverage; full `make test` passed at 83.83% scoped coverage. `.coverage` is ignored by `.gitignore`, was untracked, and has been removed from the workspace after verification.

**R12 status:** ✅ **DONE (2026-06-30)** — Load-tested `GET /v1/memories/search` under a concurrency sweep (`scripts/loadtest.py`, async `httpx`) to find the real bottleneck. Made the DB pool and uvicorn worker count configurable (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`, `UVICORN_WORKERS`) and added `make loadtest-up`/`make loadtest-sweep`. **The connection-pool hypothesis was falsified empirically:** pool 5+10 vs 20+40 produced the same ~44 RPS ceiling and the same linear latency growth (throughput plateaus at c≈5, below the 15-connection limit). `docker stats` under load localized the bottleneck to **API-process CPU** (api ~834% / ~8 cores while Postgres ~16%, Neo4j <1%, Redis ~3%). Root cause: `app/memory/mock_backend.py::search` ranks candidates with **pure-Python cosine** (`app/memory/retrieval.py`) instead of pgvector's `<=>`/HNSW. Scaling to 4 uvicorn workers lifted peak throughput ~44→~60 RPS (+36%) and halved p50 at c=15 (358→190 ms) but sublinearly; a two-client test confirmed the ceiling is server-side, not the load driver. Honest caveat: absolute RPS are from a shared developer laptop (Docker Desktop), so they are directional. Full evidence + ranked fixes in [docs/LOAD_TEST.md](docs/LOAD_TEST.md); next step is **R13** (move similarity into Postgres). No eval/scoring logic changed.

**Closeout status:** ✅ **DONE (2026-06-29)** — Remaining proof gaps were converted into repeatable checks/docs. Added `make hard-dependencies`, `make mem0-preflight`, `make otlp-config-check`, and `make otlp-live-check`; added [docs/HARD_DEPENDENCY_RUNBOOK.md](docs/HARD_DEPENDENCY_RUNBOOK.md), [docs/MEM0_VERIFICATION.md](docs/MEM0_VERIFICATION.md), [docs/OTLP_VERIFICATION.md](docs/OTLP_VERIFICATION.md), and [docs/PRODUCTION_HARDENING.md](docs/PRODUCTION_HARDENING.md). Hard dependency drills passed, optional OTLP collector logs showed an exported `memory.add` span, and `scripts/mem0_preflight.py` correctly returned NOT READY without package/keys while printing no secret values.

## Phase table

| Phase | Status | Evidence | Notes |
| --- | --- | --- | --- |
| 0 Plan | Done | `PLAN.md` | 11→12 phase split documented. |
| 1 Scaffold | Done | `app/` package, `pyproject.toml`, `Makefile` | Clean module layout. |
| 2 Infra + health/metrics/tracing | Done (verified 2026-06-29) | `app/observability.py`, `app/routers/health.py`, `docker-compose.yml`, `docker-compose.otel.yml`, `scripts/r6_observability_check.py`, `scripts/otlp_collector_check.py` | `/healthz` returns `postgres/neo4j/redis: up`; `/metrics` serves non-zero `memgauge_*` counters + latency histograms; API logs include `trace_id`; console span export includes `memory.add`. Optional OTLP collector override verified with collector logs containing an exported `memory.add` span. |
| 3 Postgres + Neo4j data layer | Done (verified 2026-06-29) | `app/db/init.sql`, `app/db/models.py`, `app/graph/neo4j_client.py`, `app/graph/queries.py` | Schema applied on fresh volume; eval persisted `eval_runs`/`eval_case_results`; seed wrote facts into Postgres+Neo4j; Postgres/Neo4j/Redis all reachable live. BUG-1 fixed + regression test (runs live now). |
| 4 Memory backend + hybrid retrieval + routes | Done (verified 2026-06-29) | `app/memory/mock_backend.py`, `app/memory/retrieval.py`, `app/routers/memories.py` | Hybrid scoring + per-signal breakdown verified. Supersede/UPDATE flow verified by integration test (`test_contradiction_add_creates_update_event`). |
| 5 Eval engine + sample data | Done (verified 2026-06-29) | `app/eval/*`, `data/*.jsonl` (40 cases), `data/baseline.json` | Full 40-case eval ran end-to-end against live DBs: gate **PASS**, Recall@5=0.875, p95s well under budget. Scoring/classifier also unit-verified. **R11 done:** baseline regenerated from a clean behavior-driven run (staleness 0.000, false-fact 0.125 — both now real, not label-driven). |
| 6 Report + Grafana + SLOs | Done (verified 2026-06-29) | `app/routers/report.py`, `app/templates/report.html`, `grafana/provisioning/*`, `prometheus/alerts.yml`, `docs/R6_OBSERVABILITY_RUNBOOK.md` | Server-rendered HTML report verified live (`/report/{run_id}`, 24 KB, expected markers); Prometheus scrapes non-zero MemGauge series; Grafana health is OK and the provisioned `MemGauge Overview` dashboard loads with 5 panels. |
| 7 Security / robustness | Done (verified 2026-06-29) | `app/security.py`, `app/main.py`, `tests/test_security.py`, `scripts/r7_resilience_check.py` | Token auth, rate limit, and CORS are wired and tested. Redis cache and rate limiter are fail-open. Live R7 verified 422, 404, Redis-down 503, search fail-open, and recovery. |
| 8 Tests | Done for current suite | `tests/` (11 files) | `make test-unit` passes (26 non-integration tests, 98% scoped coverage). Full `make test` passes (33 tests, 84% scoped coverage) against isolated test ports. |
| 9 CI regression gate | Done (verified live 2026-06-29) | `scripts/run_eval_ci.py`, `.github/workflows/memgauge-ci.yml` | Live gate verified against the fresh R11 baseline: clean run → **PASS, exit 0**; forced regression (`[:top_k]`→`[:1]`) → **FAIL, non-zero** (Recall@5 0.625 < 0.825 floor); reverted → PASS, exit 0. GH Actions workflow audited (no swallowed failures). |
| 10 Optional real mem0 adapter | Done (code + preflight) | `app/memory/mem0_backend.py`, `app/memory/factory.py`, `scripts/mem0_preflight.py`, `docs/MEM0_VERIFICATION.md` | Lazy import, key reads at runtime only, mirrors into shared stores. Preflight is verified to fail cleanly without optional package/keys. Real `mem0` run remains **Unverified** until local `mem0ai` + API keys are supplied. |
| 11 Docs / demo / deploy | Done | `README.md`, `DEMO.md`, `DEPLOY.md`, `LICENSE`, `docs/PRODUCTION_HARDENING.md` | Honest README (discloses demo-token security defaults, graph queries intentionally internal); screenshot placeholder removed; production hardening checklist documented. |
| 12 Dev environment | Done (verified 2026-06-29) | `.python-version`, `.tool-versions`, `docs/DEV_ENV.md`, `scripts/dev_doctor.py`, `Makefile` | Python 3.11.15 pinned for pyenv/asdf; `make doctor` verifies Python, deps, Docker, Compose, daemon reachability, and compose config. |

## R1 work (this pass — runnable-stack prep)

- Added (config/docs/startup only, **no app logic**): `make venv | stack-up | r1-eval | report | smoke | reset | r1` targets; `scripts/r1_smoke.py`; `docs/R1_RUNBOOK.md`; `docs/R1_AUDIT_NOTES.md`; clarifying header in `.env.example`.
- `make r1` chains: `up -d --build --wait` → eval (`report.md`) → HTML report (`report.html` + live URL) → smoke check.
- Statically verified here: Makefile dry-run (`make -n r1`) resolves the full chain with correct host-port env; `scripts/r1_smoke.py` parses and **fails cleanly with exit 1** when the stack is down (no false PASS).
- Pre-existing dirty-tree files (`scripts/run_eval_ci.py`, `scripts/seed_demo.py`, `data/baseline.json`, `report.md`) were modified **before** this pass — not touched by R1 work.
- **Host run complete:** the live `make r1` execution and runbook evidence table are complete on a Docker + Python 3.11 host.

## What's verified working (actually ran)

- **R1 end-to-end (2026-06-29):** `make venv && make r1` green on a Docker + Python 3.11 host. Stack all-healthy; `/healthz` all `up`; `/metrics` serves `memgauge_*`; eval gate PASS (40 cases, Recall@5=0.875); `report.html` rendered; `make smoke` → `R1 SMOKE: PASS`. Postgres/Neo4j/Redis individually reachable; seed wrote demo facts; api logs carry `trace_id`. Evidence table in [docs/R1_RUNBOOK.md](docs/R1_RUNBOOK.md) filled with observed output.
- **R11 baseline + live gate (2026-06-29):** regenerated `data/baseline.json` from a clean run; gate PASS (exit 0) against it, forced regression → non-zero, revert → exit 0. Run is deterministic (false_fact=5 reproduced across runs).
- **R6 observability (2026-06-29):** `make r6-observability` PASS. Observed `memory.add` id `3b7218af-3808-4dd9-88d9-c78f316d00e5`; direct `/metrics` add/search counts `2/2`; Prometheus add/search counts `1/1`, HTTP count `561`; Grafana dashboard `MemGauge Overview` loaded with 5 panels; API logs contained `memory.add` and `trace_id`.
- **R7 resilience (2026-06-29):** `make r7-resilience` PASS. Observed bad add payload → 422, delete missing memory → 404, seeded memory id `9c37fc2f-3e28-4698-ae80-7df233ee8a87`, Redis stopped → `/healthz` 503 with `redis=down`, search still returned the seeded memory with `cache=miss`, Redis restarted and `/healthz` recovered to all up.
- **Hard dependency health (2026-06-29):** `make hard-dependencies` PASS. Postgres stopped → `/healthz` 503 with `postgres=down`, recovery to all up; Neo4j stopped → `/healthz` 503 with `neo4j=down`, recovery to all up.
- **Optional OTLP collector (2026-06-29):** `make otlp-config-check` PASS and `make otlp-live-check` PASS. The API ran with `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`; collector debug logs contained an exported `memory.add` span from `service.name=memgauge-api`. Default stack was restored afterward with `--remove-orphans`.
- **Optional mem0 preflight (2026-06-29):** `scripts/mem0_preflight.py` returned exit 2 with NOT READY on this no-secret host because `mem0ai`, `MEM0_API_KEY`/`OPENAI_API_KEY`, and `MEMGAUGE_BACKEND=mem0` are intentionally absent. This verifies the preflight path, not the real external backend.
- Pure unit tests pass via `make test-unit`: **26 passed, 7 deselected**, coverage gate passed.
- Hybrid retrieval returns a per-signal `{vector, keyword, graph}` breakdown and correct ordering (ran `rank_memories` directly).
- Fact extraction (`extract_fact`) parses `entity/predicate/object`; sarcasm detection (`is_sarcastic`) gates `/s`-style utterances.
- Classifier branches: sarcastic-retrieved → `false_fact`, inactive-retrieved → `stale_fact`, expected-missing → `retrieval_miss`, else `none`.
- Deterministic hash embedding is a stable 384-d unit vector.
- Secrets scan: **no real secret values** in git history (only `.env.example` placeholders and the `memgauge`/`memgauge-dev` dev defaults). `.env` is gitignored; only `.env.example` tracked.

## What's partial or broken / Unverified

- **Only external-backend verification remains:** real `mem0` adapter behavior is still **Unverified** because this host intentionally lacks `mem0ai` and real API keys. The adapter is lazy, secret reads are runtime-only, and the new preflight documents exactly what is missing.
- **Security (Phase 7) is implemented:** token auth, rate limiting, and CORS are wired. R5 acceptance is verified by unit + integration tests. Production hardening still requires replacing the demo token/defaults before public exposure.
- Graph queries have no public HTTP surface by design. The former dead graph router file has been removed (R8).

## Known bugs

| ID | Description | Severity |
| --- | --- | --- |
| BUG-1 | **FIXED (2026-06-21).** `ACTIVE_FACTS` query (`app/graph/queries.py`) selected `rel.source_memory_id`, but writers set `rel.memory_id`, so `active_facts()` returned `memory_id = null`. Changed the projection to `rel.memory_id AS memory_id`; added regression test `tests/test_graph_queries.py::test_active_facts_returns_non_null_memory_id` (integration — verified by data-level reasoning here, runs live on a 3.11+Docker host). | ~~Medium~~ Resolved |
| BUG-2 | **FIXED (2026-06-21).** Eval runner force-overrode classifier output with case metadata, and the classifier had `target_failure_mode` shortcuts — staleness/false-fact rates were partly label-driven. Removed both; classification is now purely behavior-driven (observed retrieved vs. inactive/sarcastic/expected). Tests rewritten/added. **Follow-up R11 DONE (2026-06-29):** `data/baseline.json` regenerated on a live host; staleness 0.125→0.000, false-fact stays 0.125 (genuine behavior). | ~~Medium~~ Resolved |
| BUG-3 | **FIXED (2026-06-29).** Phase 7 security fields (`MEMGAUGE_API_TOKEN`, `RATE_LIMIT_PER_MIN`, `CORS_ALLOW_ORIGINS`) are now wired: protected mutating/expensive routes return 401 without a bearer token, over-limit requests return 429, and CORS honors configured origins. Added security tests and full protected-route integration coverage. | ~~Medium~~ Resolved |
| BUG-4 | **FIXED (2026-06-29).** `make test` could not run while the normal demo stack was up because `docker-compose.test.yml` reused the same host ports. Test compose now uses isolated host ports (`25432`, `27474`, `27687`, `26379`) and `TEST_ENV` points at them; full `make test` passes while the demo stack remains running. | ~~Medium~~ Resolved |

## Test & coverage status

- `make test-unit`: **26 passed, 7 deselected**, coverage **97.59%** over the scoped pure modules.
- `make test`: **33 passed**, coverage **83.83%** over the scoped app/eval + retrieval modules, using isolated Docker test services.
- `make r6-observability`: **PASS**, verifying direct metrics, Prometheus scrape, Grafana dashboard provisioning, `memory.add` span, and structured `trace_id` logs.
- `make r7-resilience`: **PASS**, verifying 422/404/503 paths, Redis-down search fail-open, and Redis recovery.
- `make hard-dependencies`: **PASS**, verifying Postgres/Neo4j outage health failures and recovery.
- `make otlp-config-check`: **PASS**, validating the optional OTLP compose override.
- `make otlp-live-check`: **PASS**, verifying API spans reach the optional collector and include `memory.add`.
- `scripts/mem0_preflight.py`: **PASS for preflight behavior** (expected exit 2 / NOT READY on this no-secret host).
- R8 graph-router cleanup verified: `app/routers/graph.py` is absent from the working tree, no code imports it, and stale docs are gone.
- `make doctor`: **PASS**, verifying local Python/deps/Docker/Compose setup.
- **R9 dev environment (2026-06-29):** observed Python 3.11.15, version-file pins, `fastapi`/`pytest` imports, Docker 29.4.3, Docker Compose v5.1.4, Docker daemon reachable, and `docker compose config` valid.
- **R10 coverage cleanup (2026-06-29):** `make test-unit` reached 97.59%; full `make test` reached 83.83%; `.coverage` was confirmed ignored/untracked and removed after the coverage runs regenerated it.
- **CI gate (R3/R11) verified live:** baseline → exit 0, forced regression → exit 1, restored → exit 0; at-tolerance edge does not false-fail. CI workflow audited: no failure-swallowing in the gate path. Live full-gate run with DBs is complete on this host.
- Coverage gates are verified: `make test-unit` reached 97.59%, and full `make test` reached 83.83%.
- `.coverage` is ignored, untracked, and currently absent from the workspace after R10 cleanup.
- Integration tests are verified live against Docker test services: add/search score breakdown, soft-delete audit trail, contradiction→UPDATE, eval persistence/reporting, multi-hop + collision Cypher, `active_facts` `memory_id`, and protected-route security.

## Outstanding security / privacy items

- Token auth exists for mutating/expensive routes, but the default `dev-token` is a local demo credential only; set a real `MEMGAUGE_API_TOKEN` before exposing the API.
- Rate limiting exists and is intentionally simple fixed-window per client IP; it is not a production abuse-control system.
- CORS middleware is wired; default empty `CORS_ALLOW_ORIGINS` allows no browser origins.
- No PII handling/redaction policy for stored memory content (acceptable for a benchmark/demo; flag if productionized).
- No secrets in repo or history (verified).

## Environment notes (what couldn't be verified and why)

- Host verification used Python 3.11.15 and Docker-backed services. The normal demo stack was already running healthy; full tests ran against the isolated `memgauge-test` compose project.
- Real `mem0` backend calls are not verified because this host has no `mem0ai` package or real API keys. Use `make mem0-preflight`, then run the documented smoke/eval flow in [docs/MEM0_VERIFICATION.md](docs/MEM0_VERIFICATION.md) once keys are available.
