# DEPLOY_PREFLIGHT — Phase 1 report (2026-07-04)

> Phase 1 of the first production deploy: repo made deploy-ready, everything
> verified locally, **no cloud resource created, no money spent**. Phase 2
> (actual Fly.io deploy + managed data services) is blocked on explicit approval.
> Target architecture: [DEPLOY.md](../DEPLOY.md) — one Fly.io API machine +
> managed Postgres/pgvector + Neo4j Aura Free + Upstash Redis, `mock` backend.

## 1. Git hygiene — done, pushed

All ~25 dirty/untracked files reviewed and committed in 11 coherent commits;
`origin/main` is up to date (was `6a4dd1b`, now includes through the deploy
config commit). Working tree clean.

| Commit | Content |
| --- | --- |
| `1b92fdb` chore | gitignore generated artifacts; untracked `report.md` (CI uploads it as a build artifact) |
| `632b066` R2 | BUG-1 `ACTIVE_FACTS` projection fix + graph integration tests |
| `552cb81` R4 | BUG-2 behavior-driven classifier (runner override + shortcuts removed) |
| `f89ab02` R5 | Phase 7 security: token auth, rate limit, CORS (+ BUG-4 test-port isolation) |
| `3d49e02` R8 | dead graph router removed |
| `ef454e7` R1/R9/R11 | smoke/doctor/seed/eval scripts, Python 3.11.15 pins, regenerated baseline, runbooks |
| `76e019d` R6/R7/closeout | observability/resilience/hard-dep/OTLP/mem0-preflight checks + runbooks |
| `0e8bbcd` R12 | loadtest harness, DB pool + `UVICORN_WORKERS` config |
| `d3f7deb` build | Make targets for R1–R12 flows |
| `6c07133` docs | AGENTS/CLAUDE/PROJECT/ROADMAP/STATUS + README |
| `39a3ff0` deploy | `fly.toml` + DEPLOY.md runbook tightening |

Safety checks that ran clean:

- `git ls-files --error-unmatch .env` → **fails** (`.env` not tracked). ✓
- Secret-pattern scan (`sk-`, `AKIA`, `ghp_`, private-key PEM, `xox*-`,
  password assignments) over the full committed diff and all untracked files →
  **zero hits**; only `.env.example` placeholders and documented local dev
  defaults (`memgauge`/`memgauge-dev`/`dev-token`). ✓
- `.venv/`, `.coverage`, `report.md`, `report.html`, `scratchpad/`, caches →
  all gitignored, none tracked. ✓

## 2. Deploy config — committed

- **`fly.toml`** (repo root): `shared-cpu-1x` / 512 MB, internal port 8000,
  `force_https`, auto-stop/auto-start with `min_machines_running = 0`, HTTP
  check on `GET /healthz` under `[[http_service.checks]]` (DEPLOY.md's old
  inline snippet used a stale `[checks.health]` section — corrected).
  Non-secret env pinned: `PORT=8000`, `MEMGAUGE_BACKEND=mock`.
- **Schema story documented** in DEPLOY.md: `app/db/init.sql` is applied by the
  compose entrypoint mount **locally only**; managed Postgres requires the
  one-time `psql "$DIRECT_DSN" -v ON_ERROR_STOP=1 -f app/db/init.sql` (idempotent).
- **Corrected assumption:** Neo4j constraints are **not** ensured at app
  startup — `ensure_constraints()` is called only by the eval runner and seed
  script, so on a fresh Aura instance constraints appear on the first
  `POST /v1/eval/run`. The Phase 2 verification sequence includes an eval run,
  which covers this.

## 3. Preflight verification — all green (ran 2026-07-04 on the committed code)

| Check | Result |
| --- | --- |
| `make lint` | `ruff` "All checks passed!"; `mypy` "Success: no issues found in 51 source files" |
| `make test` (integration, isolated compose) | **33 passed**, coverage 83.83% (gate ≥80%) |
| `make r1` (stack rebuild → eval → report → smoke) | Gate **PASS** (Recall@5 0.875 ≥ 0.825; search p95 7.23 ms ≤ 11.84; false-fact 0.125 ≤ 0.125); `report.html` rendered; **`R1 SMOKE: PASS`** |
| `docker build .` | Builds clean; 168 MB; `USER appuser`; CMD honors `PORT`/`UVICORN_WORKERS` |

## 4. Phase 2 — exact ordered sequence (awaiting approval; **$0, no credit card**)

> **Retargeted 2026-07-04 at the owner's request: zero-cost path.** API host is
> now **Render free** (`render.yaml`, committed) instead of Fly.io — Fly has no
> card-free tier. Everything else is unchanged. `fly.toml` stays in the repo as
> the documented paid alternative.

1. Provision free managed services (**needs owner signups — hard stop; no cards**):
   Postgres w/ pgvector (Neon or Supabase free; confirm `CREATE EXTENSION vector`),
   Neo4j Aura Free, Upstash Redis free (TLS `rediss://`).
2. One-time schema: `psql "$DIRECT_DSN" -v ON_ERROR_STOP=1 -f app/db/init.sql`; verify with `\dt`.
3. Render dashboard (owner account, free, no card): **New → Blueprint** →
   select the GitHub repo → Render reads `render.yaml` → enter the six secret
   values when prompted (`MEMGAUGE_API_TOKEN=$(openssl rand -hex 32)` revealed
   to the owner once, never committed) → Apply → Render builds the Dockerfile
   and deploys.
4. Live verification against the real `*.onrender.com` URL: `GET /healthz` all
   `up`; `GET /metrics` serves `memgauge_*`; unauthenticated `POST /v1/memories`
   → **401**; `POST /v1/eval/run` with bearer → run persists (also creates
   Neo4j constraints); `GET /report/{run_id}` renders.
5. Update STATUS.md (Phase 11 deploy → VERIFIED + URL + date), DEPLOY.md
   (actual URL + deltas), ROADMAP.md; commit + push.

**Secrets to set (names only; values generated/collected at deploy time):**
`MEMGAUGE_API_TOKEN`, `POSTGRES_DSN` (asyncpg scheme), `NEO4J_URI` (`neo4j+s://`),
`NEO4J_USER`, `NEO4J_PASSWORD`, `REDIS_URL` (`rediss://`). Non-secret env is
pinned in `render.yaml` (`MEMGAUGE_BACKEND=mock`,
`EMBEDDING_MODEL=__offline-deploy-model__`, `RATE_LIMIT_PER_MIN=60`;
`CORS_ALLOW_ORIGINS` empty default).

**Estimated setup + cost:** four provider accounts (Render, Neon/Supabase,
Neo4j Aura, Upstash) — **all free tiers, none require a credit card. Total: $0.**
Setup effort ≈ 1–2 hours. Free-tier trade-offs (accepted): Render idle
spin-down (~1 min cold start), Neon autosuspend (~1 s first query), **Aura Free
pauses after 3 days idle** (healthz 503 until manually resumed; ~30-day-paused
instances can be deleted), Upstash quota ample + Redis is fail-open.

## 5. Known caveats going into Phase 2 (no code changed — scope guard)

- **Latency-gate baseline is laptop-local.** `data/baseline.json` p95s
  (search 9.48 ms / add 50.77 ms) were measured host-side. Observed locally:
  an in-container `POST /v1/eval/run` recorded search p95 34 ms → that run's
  `passed=false` on the latency check while recall/false-fact held. On Fly with
  remote managed DBs, latencies will be higher still, so the public
  `/report/{run_id}` will likely show the latency-gate row failing. Options at
  deploy time: document it honestly on the demo, or deliberately produce a
  deploy-environment baseline. Note `set_baseline=true` writes
  `data/baseline.json` on the **container filesystem — ephemeral across Fly
  deploys**, so a deployed baseline does not survive redeployment.
- **Cold starts:** `min_machines_running = 0` means the first request after
  idle pays a machine-start delay. Acceptable for a demo; set to 1 to avoid it
  (raises cost to always-on).
- **Token policy:** the demo `dev-token` never leaves local compose; production
  token is generated at deploy (step 5) and revealed once.
