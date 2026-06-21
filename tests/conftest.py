"""Shared pytest fixtures for unit and integration tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

os.environ.setdefault(
    "POSTGRES_DSN",
    "postgresql+asyncpg://memgauge:memgauge@127.0.0.1:15432/memgauge",
)
os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:17687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "memgauge-dev")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:16379/0")
os.environ.setdefault("EMBEDDING_MODEL", "__offline-test-model__")


@pytest_asyncio.fixture
async def integration_schema() -> AsyncIterator[None]:
    """Create database schema for tests that require real services."""

    from app.db.models import Base
    from app.db.session import engine

    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()


@pytest_asyncio.fixture
async def clean_stores(integration_schema: None) -> AsyncIterator[None]:
    """Reset Postgres, Neo4j, and Redis before each integration test."""

    from app.config import get_settings
    from app.db.session import engine
    from app.graph.neo4j_client import Neo4jClient

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE eval_case_results, eval_runs, memory_events, memories "
                "RESTART IDENTITY CASCADE"
            )
        )

    settings = get_settings()
    graph = Neo4jClient(settings=settings)
    try:
        await graph.ensure_constraints()
        await graph.run_write("MATCH (node) DETACH DELETE node", {})
    finally:
        await graph.close()

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()

    yield


@pytest_asyncio.fixture
async def app_client(clean_stores: None) -> AsyncIterator[AsyncClient]:
    """HTTPX client bound directly to the FastAPI app."""

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
"""Pytest configuration placeholder."""

