"""Seed a tiny demo namespace through the memory backend."""

from __future__ import annotations

import asyncio
import json

from app.db.session import AsyncSessionLocal
from app.graph.neo4j_client import Neo4jClient
from app.memory.embeddings import get_embedding_provider
from app.memory.mock_backend import MockMemoryBackend


async def main() -> None:
    async with AsyncSessionLocal() as session:
        graph = Neo4jClient()
        await graph.ensure_constraints()
        backend = MockMemoryBackend(
            session=session,
            graph=graph,
            embeddings=get_embedding_provider(),
        )
        try:
            results = []
            for text in (
                "DemoPhaseFive likes green tea.",
                "DemoPhaseFive works at Northstar Lab.",
                "MiraPhaseFive lives in Harbor City.",
            ):
                results.append(await backend.add(text=text, user_id="demo-seed", agent_id="seed"))
            print(json.dumps({"seeded": results}, indent=2))
        finally:
            await graph.close()


if __name__ == "__main__":
    asyncio.run(main())
