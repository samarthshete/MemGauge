"""R6 observability verification against a live MemGauge stack.

Checks, in order:

1. API is healthy.
2. A real protected ``POST /v1/memories`` and public search complete.
3. Direct ``/metrics`` exposes non-zero add/search histogram counts.
4. Prometheus has scraped the same non-zero series.
5. Grafana is healthy and the provisioned MemGauge dashboard is loadable.
6. API container logs include a console-exported ``memory.add`` span.

Usage:
    API_URL=http://127.0.0.1:18000 \
    PROM_URL=http://127.0.0.1:19090 \
    GRAFANA_URL=http://127.0.0.1:13000 \
    API_TOKEN=dev-token \
    python scripts/r6_observability_check.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_URL = os.environ.get("API_URL", "http://127.0.0.1:18000").rstrip("/")
PROM_URL = os.environ.get("PROM_URL", "http://127.0.0.1:19090").rstrip("/")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://127.0.0.1:13000").rstrip("/")
API_TOKEN = os.environ.get("API_TOKEN", "dev-token")
TIMEOUT = 10
POLL_SECONDS = 35


def _fail(check: str, detail: str) -> None:
    print(f"  x {check}: {detail}")
    sys.exit(1)


def _request(
    method: str,
    url: str,
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
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        _fail("connect", f"could not reach {url}: {exc}. Is the stack up?")
        raise


def _get_json(url: str) -> dict[str, Any]:
    status, body = _request("GET", url)
    if status != 200:
        _fail("http", f"GET {url} returned {status}: {body[:300]}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        _fail("json", f"GET {url} returned invalid JSON: {exc}")
    return payload


def _parse_metric_count(metrics_body: str, metric_name: str, operation: str) -> float:
    pattern = re.compile(
        rf"^{re.escape(metric_name)}\{{[^}}]*operation=\"{re.escape(operation)}\"[^}}]*\}}\s+"
        r"(?P<value>[0-9.eE+-]+)$"
    )
    for line in metrics_body.splitlines():
        match = pattern.match(line)
        if match:
            return float(match.group("value"))
    return 0.0


def _prom_query(query: str) -> float:
    encoded = urllib.parse.urlencode({"query": query})
    payload = _get_json(f"{PROM_URL}/api/v1/query?{encoded}")
    if payload.get("status") != "success":
        _fail("prometheus", f"query failed: {query}: {payload}")
    result = payload.get("data", {}).get("result", [])
    if not result:
        return 0.0
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        _fail("prometheus", f"unexpected query result for {query}: {result} ({exc})")
    return 0.0


def _wait_for_prometheus(query: str, *, minimum: float = 1.0) -> float:
    deadline = time.monotonic() + POLL_SECONDS
    last_value = 0.0
    while time.monotonic() < deadline:
        last_value = _prom_query(query)
        if last_value >= minimum:
            return last_value
        time.sleep(3)
    _fail("prometheus", f"{query!r} stayed at {last_value}; expected >= {minimum}")
    return last_value


def _docker_logs() -> str:
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "--tail=800", "api"],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("docker-logs", f"could not read api logs: {exc}")
    if result.returncode != 0:
        _fail("docker-logs", result.stderr.strip() or result.stdout.strip())
    return result.stdout


def main() -> None:
    print(f"R6 observability check against api={API_URL} prom={PROM_URL} grafana={GRAFANA_URL}")

    health = _get_json(f"{API_URL}/healthz")
    for dep in ("postgres", "neo4j", "redis"):
        if health.get(dep) != "up":
            _fail("healthz", f"{dep} is {health.get(dep)!r}, expected 'up': {health}")
    print("  ok healthz: postgres/neo4j/redis all up")

    stamp = int(time.time())
    user_id = f"r6-observability-{stamp}"
    fact_text = f"R6Observability{stamp} likes green tea."
    auth = {"Authorization": f"Bearer {API_TOKEN}"}
    status, body = _request(
        "POST",
        f"{API_URL}/v1/memories",
        body={"text": fact_text, "user_id": user_id},
        headers=auth,
    )
    if status != 200:
        _fail("memory.add", f"expected 200, got {status}: {body[:300]}")
    added = json.loads(body)
    memory_id = added.get("memory", {}).get("id")
    if not memory_id:
        _fail("memory.add", f"no memory id in response: {added}")
    print(f"  ok memory.add: stored id={memory_id}")

    query = urllib.parse.urlencode(
        {"q": f"What does R6Observability{stamp} like?", "user_id": user_id}
    )
    status, body = _request("GET", f"{API_URL}/v1/memories/search?{query}")
    if status != 200:
        _fail("memory.search", f"expected 200, got {status}: {body[:300]}")
    search = json.loads(body)
    if not search.get("items"):
        _fail("memory.search", f"expected at least one result: {search}")
    print(f"  ok memory.search: {len(search['items'])} result(s), cache={search.get('cache')}")

    status, metrics = _request("GET", f"{API_URL}/metrics")
    if status != 200:
        _fail("metrics", f"expected 200, got {status}: {metrics[:300]}")
    add_count = _parse_metric_count(
        metrics,
        "memgauge_memory_operation_latency_seconds_count",
        "add",
    )
    search_count = _parse_metric_count(
        metrics,
        "memgauge_memory_operation_latency_seconds_count",
        "search",
    )
    if add_count < 1 or search_count < 1:
        _fail(
            "metrics",
            f"expected add/search counts >=1, got add={add_count} search={search_count}",
        )
    print(f"  ok metrics: add_count={add_count:g} search_count={search_count:g}")

    prom_add = _wait_for_prometheus(
        'sum(memgauge_memory_operation_latency_seconds_count{operation="add"})'
    )
    prom_search = _wait_for_prometheus(
        'sum(memgauge_memory_operation_latency_seconds_count{operation="search"})'
    )
    prom_http = _wait_for_prometheus("sum(memgauge_http_requests_total)")
    print(
        "  ok prometheus: "
        f"add_count={prom_add:g} search_count={prom_search:g} http_count={prom_http:g}"
    )

    grafana_health = _get_json(f"{GRAFANA_URL}/api/health")
    if grafana_health.get("database") != "ok":
        _fail("grafana-health", f"database is not ok: {grafana_health}")
    dashboard = _get_json(f"{GRAFANA_URL}/api/dashboards/uid/memgauge-overview")
    title = dashboard.get("dashboard", {}).get("title")
    panels = dashboard.get("dashboard", {}).get("panels", [])
    if title != "MemGauge Overview" or len(panels) < 5:
        _fail(
            "grafana-dashboard",
            f"unexpected dashboard title/panels: {title=} panels={len(panels)}",
        )
    print(f"  ok grafana: dashboard={title!r} panels={len(panels)}")

    logs = _docker_logs()
    if "memory.add" not in logs:
        _fail("otel-span", "api logs did not contain console-exported memory.add span")
    if "trace_id" not in logs:
        _fail("structured-logs", "api logs did not contain trace_id")
    print("  ok tracing/logs: api logs contain memory.add span and trace_id")

    print("R6 OBSERVABILITY: PASS")


if __name__ == "__main__":
    main()
