# R1 Runbook — Stand up MemGauge end-to-end

> Goal: a fresh developer brings the full stack up on a **Python 3.11 + Docker** host and proves it runs end-to-end, with evidence. No guessing required.
> Background and blockers: [R1_AUDIT_NOTES.md](R1_AUDIT_NOTES.md).

## Host requirements

- **Docker** + **Docker Compose v2** (`docker compose ...`). Verify: `docker --version && docker compose version`.
- **Python 3.11** specifically — the code uses `datetime.UTC` and pins `>=3.11,<3.12`. Verify: `python3.11 --version`. (If your 3.11 binary has another name, pass `PY311=<name>` to make, e.g. `make venv PY311=python3.11.9`.)
- `curl` on PATH (used by `make report`).
- Network access for the first `docker compose` image pull.
- Free local ports: **18000** (api), **15432** (postgres), **17687/17474** (neo4j), **16379** (redis), **19090** (prometheus), **13000** (grafana).

## TL;DR — one command

```bash
git clone <repo> && cd MemGauge
make venv          # build the host .venv with Python 3.11 + deps (one time)
make r1            # up --wait -> eval -> HTML report -> smoke check
```

`make r1` is the canonical R1 path. It brings the stack up and **blocks until every healthcheck passes**, runs the eval (writes `report.md`), generates the server-rendered HTML report (`report.html` + a live URL), and runs the smoke check. On success it prints `R1 SMOKE: PASS`.

## Step-by-step (with what each step proves)

### 1. Setup (one time)

```bash
cp .env.example .env          # local-only, non-secret defaults (mock backend, no API keys)
make venv                     # python3.11 -m venv .venv && pip install -e ".[dev]"
```

`make venv` is the fix for the main R1 blocker: `make seed`/`make eval`/`make smoke` run on the **host** via `.venv/bin/python` against the mapped container ports.

### 2. Start the stack and wait for health

```bash
make stack-up                 # docker compose up -d --build --wait ; docker compose ps
```

Proves: **Docker stack starts**, and **Postgres / Neo4j / Redis / api / prometheus / grafana** all reach a healthy state (the `--wait` flag blocks until healthchecks pass). `docker compose ps` should show every service `healthy`.

Independent confirmation of each service:

```bash
curl -s http://127.0.0.1:18000/healthz | jq      # {"status":"ok","postgres":"up","neo4j":"up","redis":"up"}
docker compose exec redis redis-cli ping          # PONG
docker compose exec neo4j cypher-shell -u neo4j -p memgauge-dev 'RETURN 1'   # 1
docker compose exec postgres pg_isready -U memgauge -d memgauge              # accepting connections
```

> **Schema note:** `app/db/init.sql` runs automatically on a **fresh** Postgres volume (mounted into `/docker-entrypoint-initdb.d/`). If you reuse an old volume the schema won't re-apply — run `make reset` first (see Reset). `/healthz` returning `postgres: up` plus a successful eval confirms the schema is present.

### 3. Run the eval end-to-end (gate report)

```bash
make r1-eval                  # writes report.md, prints metrics, exits non-zero on regression
```

Proves: **the eval path runs end-to-end** against the live Postgres + Neo4j + Redis, persists `eval_runs` + `eval_case_results`, compares to `data/baseline.json`, and writes the markdown gate report `report.md`. Uses deterministic offline embeddings (`EMBEDDING_MODEL=__offline-r1-model__`) for a fast, reproducible run.

### 4. Generate the server-rendered HTML report

```bash
make report                   # POSTs /v1/eval/run, captures run_id, saves report.html
```

Proves: **the server-rendered HTML report is generated/served**. Prints the `run_id` and the live URL `http://127.0.0.1:18000/report/<run_id>`, and saves a copy to `report.html`. Open the URL in a browser, or:

```bash
grep -E "<html|MemGauge|Recall@5" report.html     # expected markers present
```

### 5. Smoke check (single end-to-end assertion)

```bash
make smoke                    # scripts/r1_smoke.py
```

Proves all R1 acceptance points at once: healthz all-up, `/metrics` served, an `eval_runs` row exists, and the HTML report renders with expected markers. Prints `R1 SMOKE: PASS` and exits 0.

### 6. (Optional) Seed a demo namespace + show service comms in logs

```bash
make seed                                          # writes 3 demo memories through the backend
docker compose logs --tail=20 api                  # structured JSON logs w/ trace_id + memory.add span
```

Proves: **major services communicate** — the api writes to Postgres + Neo4j, each request emits a structured log line with a `trace_id`, and `memory.add` is traced.

## Evidence table (fill in during your run)

**Run on:** 2026-06-29 · macOS (Darwin 25.5.0) · Docker 29.4.3 · Docker Compose v5.1.4 · Python 3.11.15 — **all checks PASS**.

| Acceptance check | Command | Expected | Observed |
| --- | --- | --- | --- |
| Docker stack starts | `make stack-up` → `docker compose ps` | all services `healthy` | ✅ all 6 `Up ... (healthy)`: api, postgres, neo4j, redis, prometheus, grafana |
| Postgres reachable | `docker compose exec postgres pg_isready -U memgauge -d memgauge` | accepting connections | ✅ `/var/run/postgresql:5432 - accepting connections` |
| Neo4j reachable | `docker compose exec neo4j cypher-shell -u neo4j -p memgauge-dev 'RETURN 1'` | `1` | ✅ `1` |
| Redis reachable | `docker compose exec redis redis-cli ping` | `PONG` | ✅ `PONG` |
| App starts (3.11) | `curl -s :18000/healthz` | `{"status":"ok",...}` | ✅ `{"status":"ok","postgres":"up","neo4j":"up","redis":"up"}` |
| Metrics served | `curl -s :18000/metrics` | Prometheus exposition w/ `memgauge_*` series | ✅ `memgauge_http_requests_total{...}`, latency histograms present |
| Schema/setup ran | eval succeeds (step 3) | no relation-missing errors | ✅ eval persisted `eval_runs`/`eval_case_results`, no relation errors |
| Seed loads (optional) | `make seed` | demo memories written | ✅ wrote demo facts (e.g. `MiraPhaseFive lives_in Harbor City`) |
| Eval runs end-to-end | `make r1-eval` | metrics printed, `report.md` written | ✅ gate **PASS**, 40 cases, Recall@5=0.875; `report.md` (840 B) written |
| HTML report served | `make report` | `report.html` + live URL | ✅ `report.html` (24 KB), live at `/report/39bd837f-a041-4a4a-9c9c-fdc6d919cb32`; markers `<html`/`MemGauge`/`Recall@5` present |
| Services communicating | `docker compose logs --tail=20 api` | JSON logs w/ `trace_id` | ✅ e.g. `{"...":"request_complete",...,"trace_id":"b76ca30b...","path":"/healthz","status_code":200}` |
| Smoke passes | `make smoke` | `R1 SMOKE: PASS` | ✅ `R1 SMOKE: PASS` (healthz up, metrics served, 11 eval runs, HTML markers ok) |

## Shutdown / reset

```bash
make down            # stop containers, keep volumes
make reset           # docker compose down -v  (drops Postgres schema + Neo4j data — fresh next run)
```

## Known limitations (R1 scope)

- **Auth/rate-limit/CORS are now enforced for Phase 7 scope.** Mutating/expensive routes require `Authorization: Bearer <MEMGAUGE_API_TOKEN>`; reads/health/metrics/reports remain public by policy. The default `dev-token` is local-only — do not expose it publicly.
- **`active_facts()` BUG-1 is fixed** (R2): the query now reads `rel.memory_id` to match the writer; a regression test (`tests/test_graph_queries.py::test_active_facts_returns_non_null_memory_id`) guards it.
- **The eval's stale/false-fact classification is now behavior-driven** (BUG-2 fixed, R4): failure modes derive purely from observed backend state, never the case label. The baseline was regenerated on this host (R11) — `staleness_rate` is now 0.000 (the old 0.125 was the label artifact); `false_fact_rate` is 0.125, which is the genuine measured rate (the mock backend retrieves 5 facts flagged sarcastic).
- `mem0` backend is untouched here; R1 verifies the default secret-free `mock` backend only.

## Troubleshooting

- **`make venv` fails / wrong Python:** ensure `python3.11` resolves to 3.11.x, or pass `make venv PY311=<your-3.11>`. The committed `.venv/` (if any) is not portable — delete it and re-run `make venv`.
- **Eval errors with "relation ... does not exist":** the Postgres volume is stale and skipped `init.sql`. Run `make reset` then `make r1`.
- **`make report` can't connect:** the stack isn't healthy yet. Re-run `make stack-up` (it blocks on `--wait`) before `make report`.
- **Ports already in use:** stop whatever owns 18000/15432/17687/16379/19090/13000, or remap in `docker-compose.yml`.
- **First run slow:** image pulls + (if not using the offline model) a one-time fastembed model download. The R1 targets force the offline hash model to avoid this.
- **Grafana/Prometheus:** Grafana at `http://127.0.0.1:13000` (anonymous viewer), Prometheus at `http://127.0.0.1:19090`. Not required for the R1 PASS, but useful to eyeball.

## Security

- No secrets are committed. `.env` is gitignored; only `.env.example` (placeholders) is tracked.
- All credentials in `.env.example` (`memgauge`/`memgauge-dev`/`dev-token`) are **local-only, non-secret** defaults for the compose stack. Do not reuse them anywhere real.
- The `mock` backend needs no API keys. `mem0` keys (if you ever use that backend) are read only at runtime inside `app/memory/mem0_backend.py` and must never be committed.
