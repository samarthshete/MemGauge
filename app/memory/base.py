"""Memory backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class MemoryBackend(ABC):
    """Abstract memory backend contract used by API routes.

    Every backend mirrors its state into the shared Postgres tables, so the
    eval runner can read the audit trail regardless of which backend is active.
    """

    session: AsyncSession

    @abstractmethod
    async def add(
        self,
        *,
        text: str,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        infer: bool = True,
        sarcasm: bool = False,
    ) -> dict[str, Any]:
        """Add or update a memory."""

    @abstractmethod
    async def search(self, *, q: str, user_id: str, top_k: int = 5) -> dict[str, Any]:
        """Search active memories."""

    @abstractmethod
    async def list(self, *, user_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List active memories for a user."""

    @abstractmethod
    async def delete(self, *, memory_id: UUID) -> dict[str, Any]:
        """Soft-delete a memory."""
