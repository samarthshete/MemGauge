"""Seed a tiny demo namespace through the memory backend."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "POSTGRES_DSN",
    "postgresql+asyncpg://memgauge:memgauge@127.0.0.1:15432/memgauge",
)
os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:17687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "memgauge-dev")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:16379/0")

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.graph.neo4j_client import Neo4jClient  # noqa: E402
from app.memory.embeddings import get_embedding_provider  # noqa: E402
from app.memory.mock_backend import MockMemoryBackend  # noqa: E402


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
