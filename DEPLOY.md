# Deploying MemGauge

MemGauge is designed to deploy as **one lightweight artifact**: the API container
plus three managed data services. The observability stack (Prometheus + Grafana)
stays **local-dev only** (`docker compose up`) — it is not part of the production
deploy. The public demo surface is the **API + the `/report/{run_id}` page**.

> Do not stand up six services in production. One API machine + managed
> Postgres/Neo4j/Redis is the whole footprint.

## Production-ready image

The `Dockerfile` is production-runnable:

- **Non-root**: runs as `appuser` (uid 10001).
- **Healthcheck**: `HEALTHCHECK` probes `/healthz` (green only when Postgres,
  Neo4j, and Redis are reachable).
- **Env-driven**: all config comes from environment variables (`app/config.py`);
  `PORT` is overridable.

```bash
docker build -t memgauge:latest .
docker run --rm -p 8000:8000 \
  -e POSTGRES_DSN=postgresql+asyncpg://USER:PASS@HOST:5432/memgauge \
  -e NEO4J_URI=neo4j+s://XXXX.databases.neo4j.io \
  -e NEO4J_USER=neo4j -e NEO4J_PASSWORD=... \
  -e REDIS_URL=rediss://default:PASS@HOST:6379 \
  -e MEMGAUGE_API_TOKEN=replace-me \
  memgauge:latest
```

## Chosen path: zero-cost, no credit card — Render + free managed data services

**Target:** API on **Render** (free web service, `render.yaml` committed at the
repo root — runs the Dockerfile unchanged), **Neon or Supabase** Postgres with
pgvector, **Neo4j Aura Free**, **Upstash** Redis. **Every provider's free tier
requires no credit card. Total cost: $0.**

Accepted free-tier trade-offs (documented, not hidden):

- **Render free** spins the service down after ~15 min idle; the first request
  after that pays a ~1 min cold start.
- **Neon free** autosuspends compute when idle; the first query after resume
  adds ~1 s.
- **Neo4j Aura Free pauses after 3 days of inactivity.** While paused,
  `/healthz` reports `neo4j: down` (503) until you resume it in the Aura
  console — Render's health check will show the service unhealthy during that
  window. Long-paused (~30 days) Aura Free instances can be deleted by Neo4j.
- **Upstash free** command quota is ample here; the app treats Redis as
  fail-open, so even an exhausted quota degrades to cache-miss, not an outage.

### 1. Provision the managed services

| Service | Provider | What you need |
| --- | --- | --- |
| Postgres + pgvector | Neon / Supabase (free) | a connection string; confirm the `vector` extension is available |
| Graph | Neo4j Aura Free | `neo4j+s://...` URI, user, password |
| Redis | Upstash (free) | a `rediss://...` TLS URL |

### 2. Initialize the database schema (one-time, required)

**Locally**, `app/db/init.sql` is applied automatically because `docker-compose.yml`
mounts it into the Postgres container's `/docker-entrypoint-initdb.d/`. **Managed
Postgres will never run it** — there is no app-side migration step, so you must
apply it once by hand against the managed instance, using its **direct** (plain
`postgresql://`, non-async) URL:

```bash
psql "postgresql://USER:PASS@HOST:5432/memgauge" -v ON_ERROR_STOP=1 -f app/db/init.sql
```

It is idempotent (`CREATE ... IF NOT EXISTS`), so re-running is safe. Verify with
`psql ... -c '\dt'` — expect `memories`, `memory_events`, `eval_runs`,
`eval_case_results`.

**Neo4j needs no manual schema step**, but note the timing: uniqueness constraints
are created by `Neo4jClient.ensure_constraints()`, which is called by the eval
runner (`app/eval/runner.py`) and the seed script — **not at app startup**. On a
fresh Aura instance the constraints appear on the first `POST /v1/eval/run` (or
`make seed`), so run one eval as part of deploy verification.

### 3. Configure Render

A ready `render.yaml` Blueprint is committed at the repo root: free plan,
`runtime: docker` (the existing Dockerfile deploys unchanged; Render injects
`PORT` and the CMD honors it), health check on `/healthz`, `autoDeploy: false`
(deploys are explicit, not per-push), and non-secret env pinned
(`MEMGAUGE_BACKEND=mock`, `EMBEDDING_MODEL=__offline-deploy-model__`,
`RATE_LIMIT_PER_MIN=60`). Secret env vars are declared `sync: false`, so Render
prompts for their values at blueprint creation and never stores them in git.

`/healthz` returns 503 until Postgres, Neo4j, **and** Redis are all reachable —
so finish steps 1–2 and have all secret values ready before the first deploy,
or the service will never pass its health check.

Deploy flow: push to GitHub → Render dashboard → **New → Blueprint** → select
the repo → Render reads `render.yaml` → enter the six secret values when
prompted → Apply.

### 4. Set secrets and deploy

All runtime configuration is env-driven (`app/config.py`). Non-secret values
live in `render.yaml`; everything else is entered as Render secret env vars —
never committed, never baked into the image:

| Secret | Value shape | Notes |
| --- | --- | --- |
| `MEMGAUGE_API_TOKEN` | strong random string | Generate at deploy time, e.g. `openssl rand -hex 32`. **Never** the local `dev-token`. Protects `POST /v1/memories`, `DELETE /v1/memories/{id}`, `POST /v1/eval/run`. |
| `POSTGRES_DSN` | `postgresql+asyncpg://USER:PASS@HOST:5432/memgauge` | Must use the **async** `postgresql+asyncpg://` scheme. |
| `NEO4J_URI` | `neo4j+s://XXXX.databases.neo4j.io` | Aura uses the TLS `neo4j+s://` scheme. |
| `NEO4J_USER` / `NEO4J_PASSWORD` | from Aura | |
| `REDIS_URL` | `rediss://default:PASS@HOST:6379` | Upstash uses TLS `rediss://`. |
| `EMBEDDING_MODEL` | `__offline-deploy-model__` (recommended) | A name fastembed can't load (the `__offline-*-model__` convention) makes `EmbeddingProvider` fall back to the deterministic 384-d hash embedder — no model download, matches what CI/R1 verified, fits the 512 MB VM. Set `BAAI/bge-small-en-v1.5` only if you deliberately want fastembed to download the real model. |
| `CORS_ALLOW_ORIGINS` | empty (default) | Empty = no browser origins allowed. Set a comma-separated origin list only if a browser client needs the API. |
| `RATE_LIMIT_PER_MIN` | `60` (default) | Redis-backed fixed-window per client IP, fail-open. |

Enter the values when the Blueprint prompts for the `sync: false` keys
(generate the token with `openssl rand -hex 32`), then Apply — Render builds
the Dockerfile and deploys. (`EMBEDDING_MODEL` and `RATE_LIMIT_PER_MIN` are
already pinned as non-secret env in `render.yaml`; `CORS_ALLOW_ORIGINS` is
omitted so the empty default applies.)

> Connection-string notes: the app uses the **async** Postgres driver, so the DSN
> must start with `postgresql+asyncpg://`. Neo4j Aura uses the TLS `neo4j+s://`
> scheme; Upstash Redis uses `rediss://`.

### 5. Verify

```bash
curl https://memgauge.onrender.com/healthz     # -> {"status":"ok", ...}  (first hit after idle: ~1 min cold start)
# Unauthenticated mutation must be rejected:
curl -i -X POST https://memgauge.onrender.com/v1/memories -H 'content-type: application/json' -d '{}'   # -> 401
# Generate a run (also creates the Neo4j constraints on first execution), then view the report page:
curl -X POST https://memgauge.onrender.com/v1/eval/run \
  -H "authorization: Bearer $MEMGAUGE_API_TOKEN" \
  -H 'content-type: application/json' -d '{"dataset":"all"}'
# open https://memgauge.onrender.com/report/<run_id>
```

(The exact hostname is assigned by Render — `memgauge.onrender.com` or a
suffixed variant; record the real one here after the first deploy.)

## Alternative: Fly.io (paid, ~$0–5/mo — requires a credit card)

A ready `fly.toml` is also committed for deploying on Fly instead: same image,
same secrets (set via `fly secrets set` after `fly launch --no-deploy`, then
`fly deploy`). Fly has no card-free tier, which is why Render is the chosen
zero-cost path; prefer Fly if you want no idle spin-down semantics and are
willing to pay a few dollars a month.

## What is intentionally not deployed

- **Prometheus & Grafana** — local-dev only (`docker compose up`). `/metrics` is
  still exposed by the API, so a managed scraper (e.g. Grafana Cloud / Fly metrics)
  can be pointed at it later, but the demo does not host them.
- **mem0 backend** — keep `MEMGAUGE_BACKEND=mock` in the public deploy so no
  secrets/LLM keys are required. Run `mem0` locally with your own key.
