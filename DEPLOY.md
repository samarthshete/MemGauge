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

## One concrete path: Fly.io + managed data services

**Target:** API on **Fly.io**, **managed Postgres with pgvector** (Supabase or
Neon), **Neo4j Aura Free**, **managed Redis** (Upstash).

### 1. Provision the managed services

| Service | Provider | What you need |
| --- | --- | --- |
| Postgres + pgvector | Supabase / Neon | a connection string; confirm the `vector` extension is available |
| Graph | Neo4j Aura Free | `neo4j+s://...` URI, user, password |
| Redis | Upstash | a `rediss://...` TLS URL |

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

### 3. Configure Fly

A ready `fly.toml` is committed at the repo root (one `shared-cpu-1x` machine,
internal port 8000, HTTP health check on `/healthz`, `MEMGAUGE_BACKEND=mock`
pinned as non-secret env). Note the health check lives under
`[[http_service.checks]]` (current Fly syntax), and `/healthz` returns 503 until
Postgres, Neo4j, **and** Redis are all reachable — so finish steps 1–2 and set
all secrets before the first `fly deploy`, or the release will never pass its
health check.

### 4. Set secrets and deploy

All runtime configuration is env-driven (`app/config.py`). Non-secret values
(`PORT`, `MEMGAUGE_BACKEND=mock`) live in `fly.toml`; everything else is set as
Fly secrets — never committed, never baked into the image:

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

```bash
fly launch --no-deploy            # registers the app from the committed fly.toml
fly secrets set \
  MEMGAUGE_API_TOKEN="$(openssl rand -hex 32)" \
  POSTGRES_DSN="postgresql+asyncpg://USER:PASS@HOST:5432/memgauge" \
  NEO4J_URI="neo4j+s://XXXX.databases.neo4j.io" \
  NEO4J_USER="neo4j" \
  NEO4J_PASSWORD="..." \
  REDIS_URL="rediss://default:PASS@HOST:6379" \
  EMBEDDING_MODEL="__offline-deploy-model__" \
  RATE_LIMIT_PER_MIN="60"
fly deploy
```

> Connection-string notes: the app uses the **async** Postgres driver, so the DSN
> must start with `postgresql+asyncpg://`. Neo4j Aura uses the TLS `neo4j+s://`
> scheme; Upstash Redis uses `rediss://`.

### 5. Verify

```bash
curl https://memgauge.fly.dev/healthz          # -> {"status":"ok", ...}
# Optionally generate a run, then view the report page:
curl -X POST https://memgauge.fly.dev/v1/eval/run -H 'content-type: application/json' -d '{"dataset":"all"}'
# open https://memgauge.fly.dev/report/<run_id>
```

## What is intentionally not deployed

- **Prometheus & Grafana** — local-dev only (`docker compose up`). `/metrics` is
  still exposed by the API, so a managed scraper (e.g. Grafana Cloud / Fly metrics)
  can be pointed at it later, but the demo does not host them.
- **mem0 backend** — keep `MEMGAUGE_BACKEND=mock` in the public deploy so no
  secrets/LLM keys are required. Run `mem0` locally with your own key.
