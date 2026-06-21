"""Evaluation report assembly."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalCaseResult, EvalRun

BASELINE_PATH = Path("data/baseline.json")
METRICS = (
    ("recall_at_5", "Recall@5", "higher"),
    ("precision", "Precision", "higher"),
    ("staleness_rate", "Staleness rate", "lower"),
    ("false_fact_rate", "False fact rate", "lower"),
    ("p95_search_ms", "Search p95", "lower"),
    ("p95_add_ms", "Add p95", "lower"),
)


async def build_report(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    run = await session.get(EvalRun, UUID(run_id))
    if run is None:
        return None
    results = (
        await session.scalars(
            select(EvalCaseResult)
            .where(EvalCaseResult.run_id == run.id)
            .order_by(EvalCaseResult.case_id)
        )
    ).all()
    counts = Counter(result.failure_mode for result in results)
    run_payload = {
        "id": str(run.id),
        "created_at": run.created_at.isoformat(),
        "dataset_name": run.dataset_name,
        "git_sha": run.git_sha,
        "backend_mode": run.backend_mode,
        "recall_at_5": run.recall_at_5,
        "precision": run.precision,
        "staleness_rate": run.staleness_rate,
        "false_fact_rate": run.false_fact_rate,
        "p95_search_ms": run.p95_search_ms,
        "p95_add_ms": run.p95_add_ms,
        "total_cases": run.total_cases,
        "passed": run.passed,
        "baseline_id": str(run.baseline_id) if run.baseline_id else None,
    }
    baseline = read_baseline()
    return {
        "run": run_payload,
        "baseline": baseline,
        "metric_rows": metric_rows(run_payload, baseline),
        "failure_mode_counts": dict(counts),
        "cases": [
            {
                "case_id": result.case_id,
                "failure_mode": result.failure_mode,
                "expected": result.expected,
                "retrieved": result.retrieved,
                "score": result.score,
                "latency_ms": result.latency_ms,
            }
            for result in results
        ],
    }


def read_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def metric_rows(run: dict[str, Any], baseline: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, label, direction in METRICS:
        value = float(run[key])
        baseline_value = float((baseline or {}).get(key, value) or value or 0)
        denominator = max(abs(value), abs(baseline_value), 0.000001)
        value_width = min(100.0, max(2.0, (abs(value) / denominator) * 100))
        baseline_width = min(100.0, max(2.0, (abs(baseline_value) / denominator) * 100))
        rows.append(
            {
                "key": key,
                "label": label,
                "direction": direction,
                "value": value,
                "baseline": baseline_value,
                "value_width": round(value_width, 2),
                "baseline_width": round(baseline_width, 2),
                "unit": "ms" if key.endswith("_ms") else "",
            }
        )
    return rows
