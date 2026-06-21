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

### 2. Initialize the database schema

The schema (tables, pgvector extension, indexes) lives in `app/db/init.sql`. Apply
it once against the managed Postgres using its **direct** (non-async) URL:

```bash
psql "postgresql://USER:PASS@HOST:5432/memgauge" -v ON_ERROR_STOP=1 -f app/db/init.sql
```

### 3. Configure Fly

`fly.toml` (one small machine is plenty):

```toml
app = "memgauge"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"

[checks.health]
  type = "http"
  path = "/healthz"
  interval = "30s"
  timeout = "5s"
  grace_period = "20s"
```

### 4. Set secrets and deploy

Secrets are injected as env vars — never baked into the image:

```bash
fly launch --no-deploy            # creates the app from fly.toml
fly secrets set \
  POSTGRES_DSN="postgresql+asyncpg://USER:PASS@HOST:5432/memgauge" \
  NEO4J_URI="neo4j+s://XXXX.databases.neo4j.io" \
  NEO4J_USER="neo4j" \
  NEO4J_PASSWORD="..." \
  REDIS_URL="rediss://default:PASS@HOST:6379" \
  MEMGAUGE_API_TOKEN="replace-me"
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
