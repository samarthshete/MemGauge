# Production Hardening Checklist

MemGauge is currently a local/demo-grade observability and regression-gate
service. Before exposing it beyond localhost, complete this checklist.

## Required Before Public Exposure

- Set a non-default `MEMGAUGE_API_TOKEN`.
- Set `CORS_ALLOW_ORIGINS` to an explicit allow-list.
- Keep `MEMGAUGE_BACKEND=mock` unless you intentionally provision real `mem0`
  credentials outside the repo.
- Store secrets only in your deployment platform's secret manager.
- Define a retention policy for `memory_events`, `eval_runs`, and
  `eval_case_results`.
- Decide whether memory contents may contain PII; if yes, add redaction or
  classification before storage.
- Configure an OTLP collector or hosted tracing backend if stdout spans are not
  sufficient.
- Put the API behind TLS and network-level access controls.
- Confirm backup/restore for Postgres and Neo4j.

## Already Present

- Bearer-token protection for mutating/expensive routes.
- Fixed-window rate limiting with Redis and fail-open fallback.
- CORS middleware with empty allow-list by default.
- Local-only compose port bindings on `127.0.0.1`.
- Secret-free default `mock` backend.
- `.env` ignored; `.env.example` contains only local placeholder values.
