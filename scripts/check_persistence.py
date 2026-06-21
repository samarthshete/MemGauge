"""Verify Phase 3 persistence connectivity and empty graph queries."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import engine
from app.graph.neo4j_client import Neo4jClient


async def main() -> None:
    async with engine.connect() as connection:
        tables = (
            await connection.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                    """
                )
            )
        ).scalars()
        print({"postgres_tables": list(tables)})

    graph = Neo4jClient()
    try:
        await graph.verify_connectivity()
        await graph.ensure_constraints()
        results = {
            "related_entities": await graph.related_entities("empty", hops=2),
            "entity_resolution_collisions": await graph.entity_resolution_collisions(threshold=1),
            "active_facts": await graph.active_facts("empty"),
        }
        print({"neo4j_query_results": results})
    finally:
        await graph.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
