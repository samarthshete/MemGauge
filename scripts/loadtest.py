"""Closed-loop async load driver for MemGauge.

Drives ``GET /v1/memories/search`` at a fixed concurrency (number of in-flight
requests) for a fixed duration and reports client-side p50/p95/p99 latency,
throughput, and error rate. A ``--sweep`` runs a ladder of concurrency levels so
the connection-pool saturation knee is visible as a single table.

Why a unique nonce per query: the search route caches on
``memory-search:{user_id}:{top_k}:{q}`` (see app/routers/memories.py). Reusing the
same query would serve from Redis and never touch Postgres, hiding the
connection-pool bottleneck. Appending a nonce forces a cache miss every request so
load actually reaches the database. ``--write-ratio`` mixes in DB-bound
``POST /v1/memories`` calls for a realistic read/write blend.

Server-side corroboration: the script snapshots the Prometheus
``memgauge_memory_operation_latency_seconds`` sum/count for the search operation
before and after each level, reporting the server-observed mean over the window.

No new dependency: uses ``httpx`` (already required) + ``asyncio``.

Examples:
    python scripts/loadtest.py --concurrency 50 --duration 10
    python scripts/loadtest.py --sweep 1,5,10,15,20,50,100,200 --duration 8 \
        --out scratchpad/loadtest_before.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:18000"
DEFAULT_TOKEN = "dev-token"
DEFAULT_USER = "loadtest-user"
DEFAULT_SWEEP = [1, 5, 10, 15, 20, 50, 100, 200]
SEED_COUNT = 50
SEARCH_TERMS = ["tea", "coffee", "lab", "city", "mug", "notes", "vale", "lantern"]


@dataclass
class LevelResult:
    concurrency: int
    requests: int
    errors: int
    elapsed_s: float
    latencies_ms: list[float] = field(default_factory=list)
    server_mean_ms: float | None = None

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.latencies_ms)
        return {
            "concurrency": self.concurrency,
            "requests": self.requests,
            "errors": self.errors,
            "error_rate": round(self.errors / self.requests, 4) if self.requests else 0.0,
            "rps": round(self.requests / self.elapsed_s, 1) if self.elapsed_s else 0.0,
            "p50_ms": round(_pct(ordered, 50), 2),
            "p95_ms": round(_pct(ordered, 95), 2),
            "p99_ms": round(_pct(ordered, 99), 2),
            "max_ms": round(ordered[-1], 2) if ordered else 0.0,
            "server_mean_ms": round(self.server_mean_ms, 2)
            if self.server_mean_ms is not None
            else None,
        }


def _pct(ordered: list[float], pct: float) -> float:
    if not ordered:
        return 0.0
    rank = (pct / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


async def _seed(client: httpx.AsyncClient, token: str, user_id: str) -> int:
    """Populate a user namespace so search has rows to rank. Returns rows added."""
    headers = {"Authorization": f"Bearer {token}"}
    added = 0
    for i in range(SEED_COUNT):
        term = SEARCH_TERMS[i % len(SEARCH_TERMS)]
        text = f"LoadUser{i} likes {term} number {i}."
        resp = await client.post(
            "/v1/memories",
            headers=headers,
            json={"text": text, "user_id": user_id, "agent_id": "loadtest"},
        )
        if resp.status_code < 300:
            added += 1
    return added


async def _read_search_metric(client: httpx.AsyncClient) -> tuple[float, float]:
    """Return (sum_seconds, count) for the search operation histogram, or (0, 0)."""
    try:
        resp = await client.get("/metrics")
    except httpx.HTTPError:
        return 0.0, 0.0
    total_sum = total_count = 0.0
    for line in resp.text.splitlines():
        if not line.startswith("memgauge_memory_operation_latency_seconds"):
            continue
        if 'operation="search"' not in line:
            continue
        if line.startswith("memgauge_memory_operation_latency_seconds_sum"):
            total_sum = float(line.rsplit(" ", 1)[-1])
        elif line.startswith("memgauge_memory_operation_latency_seconds_count"):
            total_count = float(line.rsplit(" ", 1)[-1])
    return total_sum, total_count


async def _run_level(
    client: httpx.AsyncClient,
    *,
    token: str,
    user_id: str,
    concurrency: int,
    duration: float,
    write_ratio: float,
    timeout: float,
) -> LevelResult:
    result = LevelResult(concurrency=concurrency, requests=0, errors=0, elapsed_s=0.0)
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.perf_counter() + duration
    counter = {"n": 0}

    async def worker(worker_id: int) -> None:
        local = worker_id * 1_000_000
        while time.perf_counter() < deadline:
            nonce = local + counter["n"]
            counter["n"] += 1
            term = SEARCH_TERMS[nonce % len(SEARCH_TERMS)]
            started = time.perf_counter()
            try:
                if write_ratio and (nonce % 100) < (write_ratio * 100):
                    resp = await client.post(
                        "/v1/memories",
                        headers=headers,
                        json={
                            "text": f"WriteUser{nonce} likes {term} n{nonce}.",
                            "user_id": user_id,
                            "agent_id": "loadtest",
                        },
                    )
                else:
                    # Unique nonce -> Redis cache miss -> exercises Postgres/pool.
                    resp = await client.get(
                        "/v1/memories/search",
                        params={"q": f"{term} {nonce}", "user_id": user_id, "top_k": 5},
                    )
                elapsed_ms = (time.perf_counter() - started) * 1000
                result.latencies_ms.append(elapsed_ms)
                result.requests += 1
                if resp.status_code >= 300:
                    result.errors += 1
            except (httpx.HTTPError, TimeoutError):
                result.requests += 1
                result.errors += 1

    started_all = time.perf_counter()
    sum0, count0 = await _read_search_metric(client)
    await asyncio.gather(*(worker(i) for i in range(concurrency)))
    result.elapsed_s = time.perf_counter() - started_all
    sum1, count1 = await _read_search_metric(client)
    if count1 > count0:
        result.server_mean_ms = (sum1 - sum0) / (count1 - count0) * 1000
    return result


def _render_markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    header = (
        "| concurrency | RPS | p50 ms | p95 ms | p99 ms | max ms | errors | "
        "err rate | server mean ms |\n"
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    lines = [header]
    for r in rows:
        lines.append(
            f"| {r['concurrency']} | {r['rps']} | {r['p50_ms']} | {r['p95_ms']} | "
            f"{r['p99_ms']} | {r['max_ms']} | {r['errors']} | {r['error_rate']} | "
            f"{r['server_mean_ms']} |"
        )
    return (
        f"Backend pool: size={meta['pool_size']} overflow={meta['max_overflow']} "
        f"(~{meta['pool_size'] + meta['max_overflow']} max conns) · "
        f"duration={meta['duration']}s · write_ratio={meta['write_ratio']}\n\n"
        + "\n".join(lines)
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="MemGauge async load driver.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--user-id", default=DEFAULT_USER)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--duration", type=float, default=10.0, help="seconds per level")
    parser.add_argument("--write-ratio", type=float, default=0.0, help="fraction of writes (0..1)")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout seconds")
    parser.add_argument("--sweep", default="", help="comma list of concurrency levels")
    parser.add_argument("--no-seed", action="store_true", help="skip the seed phase")
    parser.add_argument("--out", default="", help="write results JSON to this path")
    parser.add_argument("--pool-size", type=int, default=0, help="annotation only (for the report)")
    parser.add_argument("--max-overflow", type=int, default=0, help="annotation only")
    args = parser.parse_args()

    levels = (
        [int(x) for x in args.sweep.split(",") if x.strip()] if args.sweep else [args.concurrency]
    )

    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout, limits=limits
    ) as client:
        if not args.no_seed:
            added = await _seed(client, args.token, args.user_id)
            print(f"seeded {added} memories for user_id={args.user_id}")

        rows: list[dict[str, Any]] = []
        for level in levels:
            res = await _run_level(
                client,
                token=args.token,
                user_id=args.user_id,
                concurrency=level,
                duration=args.duration,
                write_ratio=args.write_ratio,
                timeout=args.timeout,
            )
            summary = res.summary()
            rows.append(summary)
            print(
                f"c={summary['concurrency']:>4} rps={summary['rps']:>7} "
                f"p50={summary['p50_ms']:>7} p95={summary['p95_ms']:>8} "
                f"p99={summary['p99_ms']:>8} err={summary['errors']}"
            )

    meta = {
        "pool_size": args.pool_size,
        "max_overflow": args.max_overflow,
        "duration": args.duration,
        "write_ratio": args.write_ratio,
        "base_url": args.base_url,
    }
    print("\n" + _render_markdown(rows, meta))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"meta": meta, "levels": rows}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
