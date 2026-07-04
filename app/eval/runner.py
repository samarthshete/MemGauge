"""Benchmark runner for synthetic memory-quality cases."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import EvalCaseResult, EvalRun, Memory, MemoryEvent
from app.db.session import AsyncSessionLocal
from app.eval.classifier import classify_case
from app.eval.scoring import (
    false_fact_rate,
    p95,
    precision,
    recall_at_k,
    staleness_rate,
)
from app.graph.neo4j_client import Neo4jClient
from app.memory.base import MemoryBackend
from app.memory.embeddings import get_embedding_provider
from app.memory.factory import build_memory_backend

DATASETS = {
    "synthetic": [Path("data/synthetic_sessions.jsonl")],
    "adversarial": [Path("data/adversarial_cases.jsonl")],
    "all": [Path("data/synthetic_sessions.jsonl"), Path("data/adversarial_cases.jsonl")],
}
BASELINE_PATH = Path("data/baseline.json")


async def run_eval(dataset: str = "all", set_baseline: bool = False) -> dict[str, Any]:
    settings = get_settings()
    cases = load_cases(dataset)
    git_sha = os.getenv("GITHUB_SHA") or os.getenv("GIT_SHA")

    expected_ids: list[str | None] = []
    retrieved_ids: list[list[str]] = []
    failure_modes: list[str] = []
    search_latencies: list[float] = []
    add_latencies: list[float] = []
    case_payloads: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        graph = Neo4jClient(settings=settings)
        await graph.ensure_constraints()
        backend = build_memory_backend(
            session=session,
            graph=graph,
            embeddings=get_embedding_provider(),
            settings=settings,
        )
        try:
            for case in cases:
                result = await _run_case(case=case, backend=backend, graph=graph)
                expected_ids.append(result["expected_memory_id"])
                retrieved_ids.append([item["id"] for item in result["retrieved"]])
                failure_modes.append(result["failure_mode"])
                search_latencies.append(result["search_latency_ms"])
                add_latencies.extend(result["add_latencies_ms"])
                case_payloads.append(result)

            metrics = {
                "recall_at_5": recall_at_k(expected_ids, retrieved_ids, 5),
                "precision": precision(expected_ids, retrieved_ids),
                "staleness_rate": staleness_rate(failure_modes),
                "false_fact_rate": false_fact_rate(failure_modes),
                "p95_search_ms": p95(search_latencies),
                "p95_add_ms": p95(add_latencies),
                "total_cases": len(cases),
            }
            baseline = _read_baseline()
            passed, baseline_id = _compare_to_baseline(metrics, baseline, set_baseline)

            run = EvalRun(
                dataset_name=dataset,
                git_sha=git_sha,
                backend_mode=settings.memgauge_backend,
                recall_at_5=metrics["recall_at_5"],
                precision=metrics["precision"],
                staleness_rate=metrics["staleness_rate"],
                false_fact_rate=metrics["false_fact_rate"],
                p95_search_ms=metrics["p95_search_ms"],
                p95_add_ms=metrics["p95_add_ms"],
                total_cases=metrics["total_cases"],
                passed=passed,
                baseline_id=UUID(baseline_id) if baseline_id else None,
            )
            session.add(run)
            await session.flush()

            for payload in case_payloads:
                session.add(
                    EvalCaseResult(
                        run_id=run.id,
                        case_id=payload["case_id"],
                        failure_mode=payload["failure_mode"],
                        expected=payload["expected"],
                        retrieved=payload["retrieved"],
                        score=payload["score"],
                        latency_ms=payload["search_latency_ms"],
                    )
                )
            await session.commit()
            await session.refresh(run)

            summary = {
                "run_id": str(run.id),
                "dataset": dataset,
                "passed": passed,
                **metrics,
                "failure_mode_counts": dict(Counter(failure_modes)),
            }
            if set_baseline or baseline is None:
                _write_baseline(summary)
            return summary
        finally:
            await graph.close()


def load_cases(dataset: str) -> list[dict[str, Any]]:
    paths = DATASETS.get(dataset)
    if paths is None:
        raise ValueError(f"Unknown dataset: {dataset}")
    cases: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    cases.append(json.loads(line))
    return cases


async def _run_case(
    *,
    case: dict[str, Any],
    backend: MemoryBackend,
    graph: Neo4jClient,
) -> dict[str, Any]:
    await _clear_user_namespace(case["user_id"], backend, graph)
    label_to_id: dict[str, str] = {}
    sarcastic_ids: set[str] = set()
    add_latencies: list[float] = []

    for seed in case["seed_memories"]:
        started_at = perf_counter()
        add_result = await backend.add(
            text=seed["text"],
            user_id=case["user_id"],
            agent_id="eval",
            run_id=case["case_id"],
            sarcasm=bool(seed.get("sarcasm", False)),
        )
        add_latencies.append((perf_counter() - started_at) * 1000)
        memory = add_result.get("memory")
        if memory is not None:
            label_to_id[seed["memory_id"]] = memory["id"]
            if seed.get("sarcasm") or seed.get("should_be_false_fact"):
                sarcastic_ids.add(memory["id"])

    expected_label = case.get("expected_memory_id")
    expected_memory_id = label_to_id.get(expected_label) if expected_label else None

    started_at = perf_counter()
    search_result = await backend.search(q=case["query"], user_id=case["user_id"], top_k=5)
    search_latency_ms = (perf_counter() - started_at) * 1000
    retrieved = search_result["items"]

    inactive_ids = await _inactive_memory_ids(case["user_id"], backend)
    # BUG-2 / ROADMAP R4: classify purely from observed backend behavior. The
    # case's target_failure_mode is NOT used to stamp the result — a case counts
    # as a failure only when the backend genuinely produced one, so staleness and
    # false-fact rates measure behavior rather than labels.
    failure_mode = classify_case(
        expected_memory_id=expected_memory_id,
        retrieved=retrieved,
        inactive_memory_ids=inactive_ids,
        sarcastic_memory_ids=sarcastic_ids,
        target_failure_mode=case.get("target_failure_mode"),
    )

    score = 1.0 if failure_mode == "none" else 0.0
    return {
        "case_id": case["case_id"],
        "expected_memory_id": expected_memory_id,
        "expected": {
            "label": expected_label,
            "memory_id": expected_memory_id,
            "target_failure_mode": case.get("target_failure_mode", "none"),
        },
        "retrieved": retrieved,
        "failure_mode": failure_mode,
        "score": score,
        "search_latency_ms": search_latency_ms,
        "add_latencies_ms": add_latencies,
    }


async def _clear_user_namespace(
    user_id: str,
    backend: MemoryBackend,
    graph: Neo4jClient,
) -> None:
    memory_ids = (
        await backend.session.scalars(select(Memory.id).where(Memory.user_id == user_id))
    ).all()
    if memory_ids:
        await backend.session.execute(
            delete(MemoryEvent).where(MemoryEvent.memory_id.in_(memory_ids))
        )
        await backend.session.execute(delete(Memory).where(Memory.id.in_(memory_ids)))
        await backend.session.commit()
    await graph.run_write(
        """
        MATCH (user:User {id: $user_id})-[owns:OWNS]->(memory:Memory)
        DETACH DELETE memory
        """,
        {"user_id": user_id},
    )
    await graph.run_write(
        """
        MATCH ()-[rel:RELATES_TO {user_id: $user_id}]->()
        DELETE rel
        """,
        {"user_id": user_id},
    )


async def _inactive_memory_ids(user_id: str, backend: MemoryBackend) -> set[str]:
    ids = (
        await backend.session.scalars(
            select(Memory.id).where(Memory.user_id == user_id, Memory.is_active.is_(False))
        )
    ).all()
    return {str(memory_id) for memory_id in ids}


def _compare_to_baseline(
    metrics: dict[str, float | int],
    baseline: dict[str, Any] | None,
    set_baseline: bool,
) -> tuple[bool, str | None]:
    if baseline is None or set_baseline:
        return True, None
    baseline_id = baseline.get("run_id")
    recall_ok = metrics["recall_at_5"] >= baseline["recall_at_5"] - 0.05
    p95_ok = metrics["p95_search_ms"] <= baseline["p95_search_ms"] * 1.25
    false_fact_ok = metrics["false_fact_rate"] <= baseline["false_fact_rate"]
    return bool(recall_ok and p95_ok and false_fact_ok), baseline_id


def _read_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline(summary: dict[str, Any]) -> None:
    BASELINE_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
