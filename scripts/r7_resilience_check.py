"""R7 resilience verification against a live MemGauge stack.

Checks, in order:

1. API starts healthy.
2. Bad add payload returns 422.
3. Deleting a missing memory returns 404.
4. A seeded memory is searchable before disruption.
5. Stopping Redis makes ``/healthz`` return 503 with ``redis=down``.
6. Search still succeeds while Redis is down (cache fail-open).
7. Redis is restarted and ``/healthz`` returns to 200/all up.

The script always attempts to restart Redis in ``finally`` after it stops it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NoReturn

API_URL = os.environ.get("API_URL", "http://127.0.0.1:18000").rstrip("/")
API_TOKEN = os.environ.get("API_TOKEN", "dev-token")
TIMEOUT = 10
RECOVERY_SECONDS = 60
MISSING_MEMORY_ID = "00000000-0000-0000-0000-000000000404"


def _fail(check: str, detail: str) -> NoReturn:
    print(f"  x {check}: {detail}")
    sys.exit(1)


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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


def _health() -> tuple[int, dict[str, Any]]:
    status, body = _request("GET", "/healthz")
    return status, _json_body("healthz", body)


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


def _assert_search(user_id: str, entity: str, expected_memory_id: str, check: str) -> None:
    query = urllib.parse.urlencode({"q": f"What does {entity} like?", "user_id": user_id})
    status, body = _request("GET", f"/v1/memories/search?{query}")
    if status != 200:
        _fail(check, f"expected 200, got {status}: {body[:300]}")
    payload = _json_body(check, body)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        _fail(check, f"expected search result, got {payload}")
    items: list[Any] = raw_items
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    if expected_memory_id not in ids:
        _fail(check, f"expected memory {expected_memory_id}, got ids={ids}")
    print(f"  ok {check}: search returned {len(items)} item(s), cache={payload.get('cache')}")


def main() -> None:
    print(f"R7 resilience check against api={API_URL}")
    redis_stopped = False
    auth = {"Authorization": f"Bearer {API_TOKEN}"}

    try:
        status, health = _health()
        if status != 200:
            _fail("healthz-initial", f"expected 200, got {status}: {health}")
        print("  ok healthz-initial: postgres/neo4j/redis all up")

        status, body = _request(
            "POST",
            "/v1/memories",
            body={"user_id": "r7-bad-input"},
            headers=auth,
        )
        if status != 422:
            _fail("bad-input-422", f"expected 422, got {status}: {body[:300]}")
        print("  ok bad-input-422: POST /v1/memories rejects missing text/messages")

        status, body = _request(
            "DELETE",
            f"/v1/memories/{MISSING_MEMORY_ID}",
            headers=auth,
        )
        if status != 404:
            _fail("missing-memory-404", f"expected 404, got {status}: {body[:300]}")
        print("  ok missing-memory-404: DELETE missing memory returns 404")

        stamp = int(time.time())
        user_id = f"r7-resilience-{stamp}"
        entity = f"R7Resilience{stamp}"
        status, body = _request(
            "POST",
            "/v1/memories",
            body={"text": f"{entity} likes oolong tea.", "user_id": user_id},
            headers=auth,
        )
        if status != 200:
            _fail("seed-memory", f"expected 200, got {status}: {body[:300]}")
        added = _json_body("seed-memory", body)
        memory_id = added.get("memory", {}).get("id")
        if not isinstance(memory_id, str):
            _fail("seed-memory", f"response did not include memory id: {added}")
        print(f"  ok seed-memory: stored id={memory_id}")

        _assert_search(user_id, entity, memory_id, "search-before-redis-stop")

        print("  .. stopping redis service for fail-open check")
        _run_compose(["stop", "redis"], "stop-redis")
        redis_stopped = True

        status, health = _health()
        if status != 503 or health.get("redis") != "down" or health.get("status") != "degraded":
            _fail("healthz-redis-down", f"expected 503 redis=down, got {status}: {health}")
        print("  ok healthz-redis-down: /healthz returns 503 with redis down")

        _assert_search(user_id, entity, memory_id, "search-redis-down-fail-open")

    finally:
        if redis_stopped:
            print("  .. restarting redis service")
            _run_compose(["start", "redis"], "start-redis")
            _wait_healthy()
            print("  ok recovery: redis restarted and /healthz is healthy")

    print("R7 RESILIENCE: PASS")


if __name__ == "__main__":
    main()
