"""Evaluation API routes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalRun
from app.deps import get_db_session
from app.eval.report import build_report
from app.eval.runner import run_eval
from app.security import require_token

router = APIRouter(prefix="/v1/eval", tags=["eval"])
DB_SESSION_DEPENDENCY = Depends(get_db_session)
# Running an eval is expensive/mutating -> protected; listing runs stays public.
REQUIRE_TOKEN = Depends(require_token)


class RunEvalRequest(BaseModel):
    dataset: str = "all"
    set_baseline: bool = False


@router.post("/run", dependencies=[REQUIRE_TOKEN])
async def run_eval_route(payload: RunEvalRequest) -> dict[str, Any]:
    return await run_eval(dataset=payload.dataset, set_baseline=payload.set_baseline)


@router.get("/runs")
async def list_eval_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    runs = (
        await session.scalars(
            select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(run.id),
                "created_at": run.created_at.isoformat(),
                "dataset_name": run.dataset_name,
                "recall_at_5": run.recall_at_5,
                "precision": run.precision,
                "staleness_rate": run.staleness_rate,
                "false_fact_rate": run.false_fact_rate,
                "p95_search_ms": run.p95_search_ms,
                "p95_add_ms": run.p95_add_ms,
                "total_cases": run.total_cases,
                "passed": run.passed,
            }
            for run in runs
        ],
        "total": len(runs),
    }


@router.get("/report/{run_id}")
async def eval_report(
    run_id: UUID,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    report = await build_report(session, str(run_id))
    if report is None:
        raise HTTPException(status_code=404, detail="eval_run_not_found")
    return report
