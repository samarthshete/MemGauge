# R6 Observability Runbook

R6 proves that MemGauge's observability path is real end-to-end:

- FastAPI emits structured request logs with `trace_id`.
- OpenTelemetry console export includes a `memory.add` span.
- `/metrics` exposes non-zero MemGauge counters/histograms.
- Prometheus scrapes those series.
- Grafana provisions the MemGauge dashboard and can load it through its API.

## Command

Start the normal stack first:

```bash
make stack-up
```

Then run:

```bash
make r6-observability
```

The target uses the host venv and local stack URLs:

- API: `http://127.0.0.1:18000`
- Prometheus: `http://127.0.0.1:19090`
- Grafana: `http://127.0.0.1:13000`
- API token: `dev-token` by default (`API_TOKEN=...` overrides it)

## Verified Evidence

Observed on 2026-06-29:

```text
R6 observability check against api=http://127.0.0.1:18000 prom=http://127.0.0.1:19090 grafana=http://127.0.0.1:13000
  ok healthz: postgres/neo4j/redis all up
  ok memory.add: stored id=3b7218af-3808-4dd9-88d9-c78f316d00e5
  ok memory.search: 1 result(s), cache=miss
  ok metrics: add_count=2 search_count=2
  ok prometheus: add_count=1 search_count=1 http_count=561
  ok grafana: dashboard='MemGauge Overview' panels=5
  ok tracing/logs: api logs contain memory.add span and trace_id
R6 OBSERVABILITY: PASS
```

## What It Checks

`scripts/r6_observability_check.py` performs one protected `POST /v1/memories`
and one public `GET /v1/memories/search`, then verifies:

- direct `/metrics` has non-zero
  `memgauge_memory_operation_latency_seconds_count{operation="add"}` and
  `{operation="search"}`;
- Prometheus query API sees non-zero add/search histogram counts and HTTP
  request count after scrape;
- Grafana `/api/health` reports database `ok`;
- Grafana `/api/dashboards/uid/memgauge-overview` returns the provisioned
  `MemGauge Overview` dashboard with five panels;
- `docker compose logs api` contains `memory.add` and `trace_id`.

## Limits

This proves the default console span export path and Grafana provisioning. It
does not prove a remote OTLP collector because `OTEL_EXPORTER_OTLP_ENDPOINT` is
empty in the default local stack.
