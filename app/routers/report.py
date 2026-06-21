"""Server-rendered evaluation report."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.eval.report import build_report

router = APIRouter(tags=["report"])
templates = Jinja2Templates(directory="app/templates")
DB_SESSION_DEPENDENCY = Depends(get_db_session)


@router.get("/report/{run_id}", response_class=HTMLResponse)
async def html_report(
    request: Request,
    run_id: UUID,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> HTMLResponse:
    report = await build_report(session, str(run_id))
    if report is None:
        raise HTTPException(status_code=404, detail="eval_run_not_found")
    return templates.TemplateResponse(
        request,
        "report.html",
        {"report": report},
    )
