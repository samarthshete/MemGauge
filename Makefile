.PHONY: up down seed eval test test-unit lint fmt doctor venv reset report smoke r1 r6-observability r7-resilience hard-dependencies mem0-preflight otlp-config-check otlp-live-check loadtest-up loadtest loadtest-sweep

PYTHON ?= .venv/bin/python
# Python 3.11 is required (code uses datetime.UTC). Override if your 3.11 is named differently.
PY311 ?= python3.11
LOCAL_ENV = PYTHONPATH=. POSTGRES_DSN=postgresql+asyncpg://memgauge:memgauge@127.0.0.1:15432/memgauge NEO4J_URI=bolt://127.0.0.1:17687 REDIS_URL=redis://127.0.0.1:16379/0
# Force the deterministic offline embeddings for a fast, reproducible R1 run.
R1_ENV = $(LOCAL_ENV) NEO4J_USER=neo4j NEO4J_PASSWORD=memgauge-dev EMBEDDING_MODEL=__offline-r1-model__
API_URL ?= http://127.0.0.1:18000
PROM_URL ?= http://127.0.0.1:19090
GRAFANA_URL ?= http://127.0.0.1:13000
# Bearer token for protected (mutating) routes. Matches the compose default.
API_TOKEN ?= dev-token
TEST_ENV = PYTHONPATH=. POSTGRES_DSN=postgresql+asyncpg://memgauge:memgauge@127.0.0.1:25432/memgauge NEO4J_URI=bolt://127.0.0.1:27687 REDIS_URL=redis://127.0.0.1:26379/0 NEO4J_USER=neo4j NEO4J_PASSWORD=memgauge-dev EMBEDDING_MODEL=__offline-test-model__
TEST_COV = --cov=app/eval --cov=app.memory.retrieval --cov-report=term-missing --cov-fail-under=80
TEST_UNIT_COV = --cov=app.eval.scoring --cov=app.eval.classifier --cov=app.memory.retrieval --cov-report=term-missing --cov-fail-under=80

up:
	docker compose up --build

down:
	docker compose down

seed:
	$(LOCAL_ENV) $(PYTHON) scripts/seed_demo.py

eval:
	$(LOCAL_ENV) $(PYTHON) scripts/run_eval_ci.py --dataset all

test:
	set -e; docker compose -p memgauge-test -f docker-compose.test.yml up -d --wait; trap 'docker compose -p memgauge-test -f docker-compose.test.yml down -v' EXIT; $(TEST_ENV) $(PYTHON) -m pytest tests $(TEST_COV)

test-unit:
	PYTHONPATH=. EMBEDDING_MODEL=__offline-test-model__ $(PYTHON) -m pytest tests -m "not integration" $(TEST_UNIT_COV)

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy app scripts tests

fmt:
	$(PYTHON) -m ruff format .

# Verify the local Python, installed deps, Docker daemon, and compose config.
doctor:
	$(PYTHON) scripts/dev_doctor.py

# ---------------------------------------------------------------------------
# R1: end-to-end runnable stack (Python 3.11 + Docker). No new app behavior.
# ---------------------------------------------------------------------------

# Create the host virtualenv used by seed/eval/smoke. Requires Python 3.11.
venv:
	$(PY311) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	@echo "venv ready: $(PYTHON) ($$(.venv/bin/python --version))"

# Bring the full stack up and BLOCK until every healthcheck passes.
stack-up:
	cp -n .env.example .env || true
	docker compose up -d --build --wait
	docker compose ps

# Run the eval through the host venv against the live stack (writes report.md).
r1-eval:
	$(R1_ENV) $(PYTHON) scripts/run_eval_ci.py --dataset all

# Generate the server-rendered HTML report: run eval via the API, capture the
# run_id, fetch /report/{run_id}, and save it to report.html as R1 evidence.
report:
	@RUN_ID=$$(curl -fsS -X POST $(API_URL)/v1/eval/run \
		-H 'content-type: application/json' \
		-H 'authorization: Bearer $(API_TOKEN)' \
		-d '{"dataset":"all"}' | $(PYTHON) -c "import sys,json;print(json.load(sys.stdin)['run_id'])"); \
	echo "eval run_id=$$RUN_ID"; \
	curl -fsS $(API_URL)/report/$$RUN_ID -o report.html; \
	echo "HTML report saved: report.html  (live at $(API_URL)/report/$$RUN_ID)"

# Minimal end-to-end smoke check for the R1 path.
smoke:
	$(R1_ENV) API_URL=$(API_URL) $(PYTHON) scripts/r1_smoke.py

# Verify R6 observability against a live stack: spans/logs, /metrics,
# Prometheus scrape, and Grafana dashboard provisioning/data source.
r6-observability:
	$(R1_ENV) API_URL=$(API_URL) PROM_URL=$(PROM_URL) GRAFANA_URL=$(GRAFANA_URL) API_TOKEN=$(API_TOKEN) $(PYTHON) scripts/r6_observability_check.py

# Verify R7 resilience against a live stack. Temporarily stops Redis, proves
# search fails open, then restarts Redis and waits for /healthz recovery.
r7-resilience:
	$(R1_ENV) API_URL=$(API_URL) API_TOKEN=$(API_TOKEN) $(PYTHON) scripts/r7_resilience_check.py

# Verify hard dependency health behavior. Temporarily stops Postgres and Neo4j
# one at a time, then restarts each and waits for recovery.
hard-dependencies:
	$(R1_ENV) API_URL=$(API_URL) $(PYTHON) scripts/hard_dependency_check.py

# Optional real Mem0 backend preflight. Requires local mem0ai + keys; never
# prints secret values and exits 2 when the optional setup is incomplete.
mem0-preflight:
	$(PYTHON) scripts/mem0_preflight.py

# Validate the optional OTLP collector compose override.
otlp-config-check:
	docker compose -f docker-compose.yml -f docker-compose.otel.yml config --quiet

# Run the optional OTLP collector override, prove exported spans reach the
# collector, then restore the default stack (console span exporter).
otlp-live-check:
	set -e; \
	restore='docker compose up -d --remove-orphans --build --wait'; \
	trap "$$restore" EXIT; \
	docker compose -f docker-compose.yml -f docker-compose.otel.yml up -d --build --wait; \
	$(R1_ENV) API_URL=$(API_URL) API_TOKEN=$(API_TOKEN) $(PYTHON) scripts/otlp_collector_check.py

# One canonical command: up -> wait healthy -> eval -> HTML report -> smoke.
r1: stack-up r1-eval report smoke
	@echo "R1 flow complete. Evidence: report.md (gate), report.html (HTML report)."

# ---------------------------------------------------------------------------
# Load test: measure search latency vs. concurrency to expose the DB connection
# pool bottleneck and the before/after of tuning it. See docs/LOAD_TEST.md.
# ---------------------------------------------------------------------------

LOADTEST_SWEEP ?= 1,5,10,15,20,50,100,200
LOADTEST_DURATION ?= 8
LOADTEST_OUT ?= scratchpad/loadtest.json

# Bring the stack up tuned for load testing (rate limiting OFF so the limiter
# does not mask the pool bottleneck). Pool size is controlled by env:
#   make loadtest-up                                   # "before": default 5+10
#   DB_POOL_SIZE=20 DB_MAX_OVERFLOW=40 make loadtest-up  # "after": 20+40
loadtest-up:
	RATE_LIMIT_PER_MIN=0 docker compose up -d --build --wait
	docker compose ps

# Single concurrency run (override with CONCURRENCY=, DURATION=, WRITE_RATIO=).
loadtest:
	$(PYTHON) scripts/loadtest.py --base-url $(API_URL) --token $(API_TOKEN) \
		--concurrency $(or $(CONCURRENCY),50) --duration $(LOADTEST_DURATION) \
		--write-ratio $(or $(WRITE_RATIO),0)

# Full concurrency ladder; writes results JSON to LOADTEST_OUT.
loadtest-sweep:
	$(PYTHON) scripts/loadtest.py --base-url $(API_URL) --token $(API_TOKEN) \
		--sweep $(LOADTEST_SWEEP) --duration $(LOADTEST_DURATION) --out $(LOADTEST_OUT)

# Tear everything down and drop volumes (resets Postgres schema + Neo4j data).
reset:
	docker compose down -v
