"""FastAPI dependencies."""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.graph.neo4j_client import Neo4jClient
from app.memory.base import MemoryBackend
from app.memory.embeddings import get_embedding_provider
from app.memory.factory import build_memory_backend


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DB_SESSION_DEPENDENCY = Depends(get_db_session)


async def get_memory_backend(
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> AsyncIterator[MemoryBackend]:
    settings = get_settings()
    graph = Neo4jClient(settings=settings)
    try:
        yield build_memory_backend(
            session=session,
            graph=graph,
            embeddings=get_embedding_provider(),
            settings=settings,
        )
    finally:
        await graph.close()
