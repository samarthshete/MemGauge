"""Health and metrics endpoints."""

from __future__ import annotations

from typing import Literal

import asyncpg
from fastapi import APIRouter, Request, Response, status
from neo4j import AsyncGraphDatabase
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import Settings
from app.db.models import EvalRun
from app.db.session import AsyncSessionLocal
from app.observability import EVAL_PASSED, EVAL_RECALL_AT_5, REGISTRY

router = APIRouter(tags=["health"])
DependencyStatus = Literal["up", "down"]


async def check_postgres(settings: Settings) -> DependencyStatus:
    try:
        connection = await asyncpg.connect(settings.asyncpg_dsn, timeout=3)
        try:
            await connection.execute("SELECT 1")
        finally:
            await connection.close()
    except Exception:
        return "down"
    return "up"


async def check_neo4j(settings: Settings) -> DependencyStatus:
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            await driver.verify_connectivity()
        finally:
            await driver.close()
    except Exception:
        return "down"
    return "up"


async def check_redis(settings: Settings) -> DependencyStatus:
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        try:
            await client.ping()
        finally:
            await client.aclose()
    except Exception:
        return "down"
    return "up"


@router.get("/healthz")
async def healthz(request: Request, response: Response) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    postgres = await check_postgres(settings)
    neo4j = await check_neo4j(settings)
    redis = await check_redis(settings)
    overall = "ok" if postgres == neo4j == redis == "up" else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": overall, "postgres": postgres, "neo4j": neo4j, "redis": redis}


@router.get("/metrics")
async def metrics() -> Response:
    await refresh_eval_metrics()
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


async def refresh_eval_metrics() -> None:
    try:
        async with AsyncSessionLocal() as session:
            latest = await session.scalar(
                select(EvalRun).order_by(EvalRun.created_at.desc()).limit(1)
            )
            if latest is None:
                EVAL_RECALL_AT_5.set(0)
                EVAL_PASSED.set(0)
                return
            EVAL_RECALL_AT_5.set(latest.recall_at_5)
            EVAL_PASSED.set(1 if latest.passed else 0)
    except Exception:
        EVAL_RECALL_AT_5.set(0)
        EVAL_PASSED.set(0)
