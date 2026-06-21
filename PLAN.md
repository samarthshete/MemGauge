# MemGauge Plan

## Understanding

- MemGauge is an observability and regression-gate service that sits beside an AI-agent memory layer modeled on Mem0.
- The goal is to instrument memory `add` and `search` operations with tracing and metrics, not to build a new memory engine.
- The service stores memory records in Postgres 16 with pgvector and stores entity relationships in Neo4j 5.
- It runs a focused benchmark that scores retrieval quality across three failure modes, then exposes a CI gate for quality and latency regressions.
- It must run locally with `docker compose up`, require zero external API keys, and keep the UI limited to one server-rendered HTML report page plus Grafana.

## Assumptions

- Because the requested parenthetical list contains 11 items while asking for 12 phases, `docs/deploy` is split into separate `docs` and `deploy` phases.
- The memory backend will provide a narrow Mem0-like interface for instrumentation and storage, but will not reimplement Mem0's memory algorithm.
- Embeddings will use fastembed locally, with a deterministic fallback for offline or constrained test environments.
- No secrets or `.env` files will be committed; only `.env.example` is allowed.
- Each phase will be implemented only after explicit confirmation to proceed.

## Build Phases

1. Scaffold
2. Infra
3. Data layer
4. Memory backend
5. Eval engine
6. Report + Grafana
7. Security
8. Tests
9. CI gate
10. Optional Mem0 adapter
11. Docs
12. Deploy
