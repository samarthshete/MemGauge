.PHONY: up down seed eval test test-unit lint fmt

PYTHON ?= .venv/bin/python
LOCAL_ENV = PYTHONPATH=. POSTGRES_DSN=postgresql+asyncpg://memgauge:memgauge@127.0.0.1:15432/memgauge NEO4J_URI=bolt://127.0.0.1:17687 REDIS_URL=redis://127.0.0.1:16379/0
TEST_ENV = $(LOCAL_ENV) NEO4J_USER=neo4j NEO4J_PASSWORD=memgauge-dev EMBEDDING_MODEL=__offline-test-model__
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
