FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser

# Install dependencies first for better layer caching. README.md is referenced by
# pyproject's `readme` field, so it must be present at install time.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY data ./data

USER appuser

EXPOSE 8000

# Readiness/health probe — green only when Postgres, Neo4j, and Redis are reachable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status==200 else 1)" || exit 1

# Config is entirely env-driven (see app/config.py). PORT is overridable.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
