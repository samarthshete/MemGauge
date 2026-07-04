"""Verify optional OTLP collector export against a live compose override stack."""

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
API_TOKEN = os.environ.get("API_TOKEN", "dev-token")
TIMEOUT = 10
POLL_SECONDS = 30


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
        _fail("connect", f"could not reach {API_URL}{path}: {exc}")
        raise


def _collector_logs() -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.otel.yml",
            "logs",
            "--tail=1000",
            "otel-collector",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    if result.returncode != 0:
        _fail("collector-logs", result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _wait_for_span(name: str) -> None:
    deadline = time.monotonic() + POLL_SECONDS
    last_logs = ""
    while time.monotonic() < deadline:
        last_logs = _collector_logs()
        if name in last_logs:
            print(f"  ok collector-span: otel-collector logs contain {name!r}")
            return
        time.sleep(2)
    _fail("collector-span", f"did not find {name!r} in collector logs: {last_logs[-1000:]}")


def main() -> None:
    print(f"OTLP collector check against api={API_URL}")
    status, body = _request("GET", "/healthz")
    if status != 200:
        _fail("healthz", f"expected 200, got {status}: {body[:300]}")
    print("  ok healthz: API healthy under OTLP override")

    stamp = int(time.time())
    auth = {"Authorization": f"Bearer {API_TOKEN}"}
    status, body = _request(
        "POST",
        "/v1/memories",
        body={"text": f"OTLPCheck{stamp} likes telemetry.", "user_id": f"otlp-{stamp}"},
        headers=auth,
    )
    if status != 200:
        _fail("memory.add", f"expected 200, got {status}: {body[:300]}")
    payload = json.loads(body)
    memory_id = payload.get("memory", {}).get("id")
    if not memory_id:
        _fail("memory.add", f"missing memory id: {payload}")
    print(f"  ok memory.add: stored id={memory_id}")
    _wait_for_span("memory.add")
    print("OTLP COLLECTOR: PASS")


if __name__ == "__main__":
    main()
