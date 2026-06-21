"""Neo4j driver wrapper and graph query helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings, get_settings
from app.graph import queries

CONSTRAINTS = (
    """
    CREATE CONSTRAINT entity_name_unique IF NOT EXISTS
    FOR (entity:Entity)
    REQUIRE entity.name IS UNIQUE
    """,
    """
    CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
    FOR (memory:Memory)
    REQUIRE memory.id IS UNIQUE
    """,
    """
    CREATE CONSTRAINT user_id_unique IF NOT EXISTS
    FOR (user:User)
    REQUIRE user.id IS UNIQUE
    """,
)


class Neo4jClient:
    """Thin async Neo4j wrapper with timeout and one retry."""

    def __init__(self, settings: Settings | None = None, timeout_seconds: float = 5.0) -> None:
        self.settings = settings or get_settings()
        self.timeout_seconds = timeout_seconds
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )

    async def close(self) -> None:
        await self.driver.close()

    async def verify_connectivity(self) -> None:
        await self._with_retry(self.driver.verify_connectivity)

    async def ensure_constraints(self) -> None:
        async with self.driver.session() as session:
            for constraint in CONSTRAINTS:
                async def run_constraint(query: str = constraint) -> Any:
                    result = await session.run(query)
                    return await result.consume()

                await self._with_retry(run_constraint)

    async def run_read(self, query: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        async with self.driver.session() as session:
            result = await self._with_retry(lambda: session.run(query, parameters))
            records = await result.data()
        return records

    async def run_write(self, query: str, parameters: dict[str, Any]) -> None:
        async with self.driver.session() as session:
            async def write_operation() -> Any:
                result = await session.run(query, parameters)
                return await result.consume()

            await self._with_retry(write_operation)

    async def related_entities(self, name: str, hops: int = 2) -> list[dict[str, Any]]:
        bounded_hops = max(1, min(hops, 2))
        return await self.run_read(
            queries.RELATED_ENTITIES,
            {"name": name, "hops": bounded_hops},
        )

    async def entity_resolution_collisions(self, threshold: int = 1) -> list[dict[str, Any]]:
        return await self.run_read(
            queries.ENTITY_RESOLUTION_COLLISIONS,
            {"threshold": threshold},
        )

    async def active_facts(self, entity: str) -> list[dict[str, Any]]:
        return await self.run_read(
            queries.ACTIVE_FACTS,
            {"entity": entity},
        )

    async def _with_retry(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                return await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("Neo4j operation failed without an exception")
