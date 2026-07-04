"""R1 end-to-end smoke check.

Proves the R1 path works against a live stack — it does NOT add product
behavior. Checks, in order:

1. API ``/healthz`` returns 200 with Postgres, Neo4j, and Redis all ``up``.
2. ``/metrics`` is served (Prometheus exposition).
3. At least one ``eval_runs`` row exists (the eval ran end-to-end) via ``/v1/eval/runs``.
4. The server-rendered HTML report for that run loads and contains expected markers.

Run AFTER ``make stack-up`` and an eval (``make r1-eval`` or ``make report``).
Usage:  API_URL=http://127.0.0.1:18000 python scripts/r1_smoke.py
Exits 0 on success, non-zero (and prints the failed check) otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://127.0.0.1:18000").rstrip("/")
TIMEOUT = 10


def _get(path: str) -> tuple[int, str]:
    url = f"{API_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        _fail("connect", f"could not reach {url}: {exc}. Is the stack up (`make stack-up`)?")
        raise  # unreachable; satisfies type checkers


def _fail(check: str, detail: str) -> None:
    print(f"  ✗ {check}: {detail}")
    sys.exit(1)


def main() -> None:
    print(f"R1 smoke check against {API_URL}")

    # 1. Health: all dependencies up.
    status, body = _get("/healthz")
    if status != 200:
        _fail("healthz", f"expected 200, got {status}: {body[:200]}")
    health = json.loads(body)
    for dep in ("postgres", "neo4j", "redis"):
        if health.get(dep) != "up":
            _fail("healthz", f"{dep} is '{health.get(dep)}' (expected 'up'): {health}")
    print(f"  ✓ healthz: status={health.get('status')} postgres/neo4j/redis all up")

    # 2. Metrics served.
    status, body = _get("/metrics")
    if status != 200 or "memgauge_" not in body:
        _fail("metrics", f"status={status}, contains memgauge_ series={'memgauge_' in body}")
    print("  ✓ metrics: Prometheus exposition served (memgauge_* series present)")

    # 3. An eval run exists.
    status, body = _get("/v1/eval/runs")
    if status != 200:
        _fail("eval/runs", f"expected 200, got {status}: {body[:200]}")
    runs = json.loads(body).get("items", [])
    if not runs:
        _fail("eval/runs", "no eval_runs found — run `make r1-eval` or `make report` first")
    run = runs[0]
    run_id = run["id"]
    print(
        f"  ✓ eval/runs: {len(runs)} run(s); latest id={run_id} "
        f"recall@5={run['recall_at_5']} passed={run['passed']} cases={run['total_cases']}"
    )

    # 4. Server-rendered HTML report loads with expected markers.
    status, body = _get(f"/report/{run_id}")
    if status != 200:
        _fail("html-report", f"expected 200, got {status}: {body[:200]}")
    markers = ("<html", "MemGauge", "Recall@5")
    missing = [m for m in markers if m not in body]
    if missing:
        _fail("html-report", f"missing expected markers {missing} in /report/{run_id}")
    print(f"  ✓ html-report: /report/{run_id} renders with markers {markers}")

    print("R1 SMOKE: PASS")


if __name__ == "__main__":
    main()
