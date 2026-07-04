# AGENTS.md — How to work in MemGauge

> **The cross-LLM contract.** Read this before touching anything. Claude Code, Codex, and any other agent share this file as the single source of truth for *how* to work here.
> Project one-liner: MemGauge is a memory-quality observability + regression-gate service beside a Mem0-style memory layer.
> Orient via: **[STATUS.md](STATUS.md)** (current reality, read first) → **[PROJECT.md](PROJECT.md)** (stable spec) → **[ROADMAP.md](ROADMAP.md)** (what's next).

## How to run

Requires **Python 3.11** (strictly `>=3.11,<3.12` — code uses `datetime.UTC`) and **Docker**.

```bash
# Full stack: API + Postgres/pgvector + Neo4j + Redis + Prometheus + Grafana
docker compose up --build          # or: make up

# Health & metrics (host ports are remapped — see docker-compose.yml)
curl http://127.0.0.1:18000/healthz
curl http://127.0.0.1:18000/metrics

# Seed a demo namespace, then run the benchmark
make seed
make eval                          # runs scripts/run_eval_ci.py --dataset all
```

Default backend is `mock` (no API keys). The optional real backend needs `MEMGAUGE_BACKEND=mem0`, the `mem0ai` package, and a key (`MEM0_API_KEY` or `OPENAI_API_KEY`) — never commit these.

## How to test / lint

```bash
make test-unit     # no services needed (uses offline hash embeddings)
make test          # integration: spins up docker-compose.test.yml services
make lint          # ruff check + mypy over app/ scripts/ tests/
make fmt           # ruff format
```

CI mirror: `.github/workflows/memgauge-ci.yml` runs unit tests + the eval gate against service containers with deterministic offline embeddings.

## Repo conventions

- **Structure:** `app/` is the package — `routers/` (HTTP), `memory/` (backends + retrieval + embeddings), `graph/` (Neo4j client + Cypher), `eval/` (runner, scoring, classifier, report), `db/` (models, session, init.sql), plus `config.py`, `observability.py`, `main.py`. Scripts in `scripts/`, datasets in `data/`, tests in `tests/`.
- **Style:** `from __future__ import annotations`; full type hints; async throughout (SQLAlchemy async, neo4j async, redis async). Ruff line length 100, rules `E,F,I,UP,B`. mypy non-strict but `warn_unused_configs`.
- **Module size:** keep modules focused and small; one responsibility each. Pure logic (scoring, retrieval, classifier) stays free of I/O so it's unit-testable without services.
- **Persistence:** soft-delete only (`is_active`/`superseded_by`); temporal graph edges (`valid_from`/`valid_to`) — never hard-delete in normal flow. Both backends mirror into the *same* Postgres + Neo4j.
- **Tests:** integration tests carry `pytestmark = pytest.mark.integration`; pure-unit tests must run with no services.

## Hard guardrails

- **No secrets** in code, config, or git history. Only `.env.example` (placeholders) is tracked. `mem0`/OpenAI keys are read lazily at runtime inside `mem0_backend.py` only.
- **`mock` stays the default backend** and must always run with zero external keys. Don't make `mem0ai` a committed dependency.
- **Never-build list:** no SPA/heavy-JS frontend, no accounts/OAuth, no extra/interchangeable databases, no streaming, no reimplementation of Mem0's memory algorithm. (Full list in PROJECT.md.)
- Don't add dependencies casually — every dep must earn its place.

## Working agreement

1. **After ANY change, update [STATUS.md](STATUS.md) and [ROADMAP.md](ROADMAP.md)** and keep them truthful. STATUS is the first file the next agent reads — it must reflect *verified* reality, with anything unrun marked `Unverified`. Never optimistically mark something working you didn't run.
2. **Work one ROADMAP item at a time.** Do the item marked `▶ NEXT` first. Do not start P-items out of priority order without flagging it explicitly and saying why.
3. **Record every bug/fix as a ROADMAP item** rather than silently fixing unrelated things.
4. **Don't change application code, deps, or fix bugs as a side effect of a docs/audit task.** Separate concerns; one change set, one purpose.
5. Distinguish **claimed** (in code/docs) from **verified** (you ran it and saw it) in everything you write.

## Note for Claude Code

`CLAUDE.md` at the repo root points here. **This file (`AGENTS.md`) is the source of truth** for how to work in MemGauge — read it first, then STATUS.md.
