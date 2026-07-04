"""Hard dependency outage verification for a live MemGauge stack.

This deliberately stops Postgres and Neo4j one at a time, verifies ``/healthz``
reports a 503 degraded state with the correct dependency down, then restarts the
service and waits for full recovery before continuing.

The script never drops volumes and always attempts recovery in ``finally``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, NoReturn

API_URL = os.environ.get("API_URL", "http://127.0.0.1:18000").rstrip("/")
TIMEOUT = 10
RECOVERY_SECONDS = 90


def _fail(check: str, detail: str) -> NoReturn:
    print(f"  x {check}: {detail}")
    sys.exit(1)


def _request(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{API_URL}{path}", timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        _fail("connect", f"could not reach {API_URL}{path}: {exc}. Is the stack up?")
        raise


def _json_body(check: str, body: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        _fail(check, f"invalid JSON response: {exc}: {body[:300]}")
    if not isinstance(payload, dict):
        _fail(check, f"expected object response, got {type(payload).__name__}")
    return payload


def _health() -> tuple[int, dict[str, Any]]:
    status, body = _request("/healthz")
    return status, _json_body("healthz", body)


def _run_compose(args: list[str], check: str) -> None:
    result = subprocess.run(
        ["docker", "compose", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=RECOVERY_SECONDS,
    )
    if result.returncode != 0:
        _fail(check, result.stderr.strip() or result.stdout.strip())


def _wait_healthy() -> dict[str, Any]:
    deadline = time.monotonic() + RECOVERY_SECONDS
    last_status = 0
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status, last_payload = _health()
        if (
            last_status == 200
            and last_payload.get("postgres") == "up"
            and last_payload.get("neo4j") == "up"
            and last_payload.get("redis") == "up"
        ):
            return last_payload
        time.sleep(2)
    _fail("recovery", f"health did not recover: status={last_status} payload={last_payload}")
    return last_payload


def _verify_initial_health() -> None:
    status, payload = _health()
    if status != 200:
        _fail("initial-health", f"expected 200, got {status}: {payload}")
    print("  ok initial-health: postgres/neo4j/redis all up")


def _check_dependency(service: str, health_key: str) -> None:
    stopped = False
    try:
        print(f"  .. stopping {service}")
        _run_compose(["stop", service], f"stop-{service}")
        stopped = True
        status, payload = _health()
        if (
            status != 503
            or payload.get("status") != "degraded"
            or payload.get(health_key) != "down"
        ):
            _fail(
                f"{service}-down-health",
                f"expected 503 degraded {health_key}=down, got {status}: {payload}",
            )
        print(f"  ok {service}-down-health: /healthz returned 503 with {health_key}=down")
    finally:
        if stopped:
            print(f"  .. restarting {service}")
            _run_compose(["start", service], f"start-{service}")
            _wait_healthy()
            print(f"  ok {service}-recovery: /healthz recovered to all up")


def main() -> None:
    print(f"Hard dependency check against api={API_URL}")
    _verify_initial_health()
    _check_dependency("postgres", "postgres")
    _check_dependency("neo4j", "neo4j")
    print("HARD DEPENDENCIES: PASS")


if __name__ == "__main__":
    main()
