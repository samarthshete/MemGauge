"""Backend selection for the MemoryBackend interface.

Keeps backend construction in one place so the API routes and the eval runner
resolve the same backend from ``MEMGAUGE_BACKEND``. ``mock`` is the default and
the only backend that runs without secrets; ``mem0`` is loaded lazily so the
``mem0ai`` package is never imported unless explicitly selected.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.graph.neo4j_client import Neo4jClient
from app.memory.base import MemoryBackend
from app.memory.embeddings import EmbeddingProvider
from app.memory.mock_backend import MockMemoryBackend


def build_memory_backend(
    *,
    session: AsyncSession,
    graph: Neo4jClient,
    embeddings: EmbeddingProvider,
    settings: Settings | None = None,
) -> MemoryBackend:
    settings = settings or get_settings()
    backend = settings.memgauge_backend.lower()

    if backend == "mock":
        return MockMemoryBackend(session=session, graph=graph, embeddings=embeddings)

    if backend == "mem0":
        from app.memory.mem0_backend import Mem0MemoryBackend

        return Mem0MemoryBackend(
            session=session,
            graph=graph,
            embeddings=embeddings,
            settings=settings,
        )

    raise NotImplementedError(f"Unknown MEMGAUGE_BACKEND={settings.memgauge_backend!r}")
