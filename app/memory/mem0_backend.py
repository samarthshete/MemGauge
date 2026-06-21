"""Real Mem0 backend.

This backend is only constructed when ``MEMGAUGE_BACKEND=mem0``. The ``mem0ai``
package and any credentials (``MEM0_API_KEY`` / ``OPENAI_API_KEY``) are imported
and read lazily *inside this module's runtime paths only* — never at import time —
so the default ``mock`` backend keeps the repository runnable with no secrets.

To make MemGauge measure real Mem0 *identically* to the mock, every Mem0
operation is mirrored into the same stores the mock uses:

* memory rows + an audit trail of ADD/UPDATE/DELETE/NOOP events in Postgres, and
* ``Entity``/``Memory``/``User`` nodes and versioned ``RELATES_TO`` edges in Neo4j.

That way the eval runner, scoring, and graph queries see Mem0's results through
the exact same lens as the mock backend.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Memory, MemoryEvent
from app.graph.neo4j_client import Neo4jClient
from app.memory.base import MemoryBackend
from app.memory.embeddings import EmbeddingProvider
from app.memory.mock_backend import (
    extract_fact,
    is_sarcastic,
    serialize_event,
    serialize_memory,
)


class Mem0MemoryBackend(MemoryBackend):
    """Adapter that drives a real Mem0 instance and mirrors state into MemGauge stores."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        graph: Neo4jClient,
        embeddings: EmbeddingProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.graph = graph
        self.embeddings = embeddings
        self.settings = settings or get_settings()
        self._client = _build_mem0_client()

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
        clean_text = text.strip()

        # Preserve the documented sarcasm -> NOOP behavior without ever sending the
        # utterance to Mem0, mirroring the mock backend exactly.
        if sarcasm or is_sarcastic(clean_text):
            return await self._record_noop(clean_text, reason="sarcasm_or_no_fact")

        raw = await asyncio.to_thread(
            self._client.add,
            [{"role": "user", "content": clean_text}],
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            infer=infer,
        )
        results = _normalize_results(raw)
        actionable = [item for item in results if item["event"] in {"ADD", "UPDATE", "DELETE"}]
        if not actionable:
            return await self._record_noop(clean_text, reason="no_fact")

        primary_memory: dict[str, Any] | None = None
        events: list[dict[str, Any]] = []
        for item in actionable:
            memory, event = await self._mirror_event(
                item=item,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
            )
            events.append(serialize_event(event))
            if primary_memory is None and memory is not None:
                primary_memory = serialize_memory(memory)
        await self.session.commit()

        fact = extract_fact(primary_memory["content"]) if primary_memory else None
        return {
            "memory": primary_memory,
            "events": events,
            "stored": primary_memory is not None,
            "fact": fact,
        }

    async def search(self, *, q: str, user_id: str, top_k: int = 5) -> dict[str, Any]:
        top_k = max(1, min(top_k, 25))
        raw = await asyncio.to_thread(
            self._client.search,
            query=q,
            user_id=user_id,
            limit=top_k,
        )
        results = _normalize_results(raw)[:top_k]
        items: list[dict[str, Any]] = []
        for item in results:
            memory_id = _coerce_uuid(item["id"])
            row = await self.session.get(Memory, memory_id)
            now = datetime.now(UTC)
            created_at = row.created_at if row is not None else now
            updated_at = row.updated_at if row is not None else now
            score = float(item.get("score") or 0.0)
            items.append(
                {
                    "id": str(memory_id),
                    "user_id": user_id,
                    "agent_id": row.agent_id if row is not None else None,
                    "run_id": row.run_id if row is not None else None,
                    "content": (row.content if row is not None else item.get("memory")) or "",
                    "score": round(score, 6),
                    # Mem0 owns ranking; expose its score in the vector slot so the
                    # response shape matches the mock's signal breakdown.
                    "signals": {"vector": round(score, 6), "keyword": 0.0, "graph": 0.0},
                    "created_at": created_at.isoformat(),
                    "updated_at": updated_at.isoformat(),
                }
            )
        return {"items": items, "total": len(items)}

    async def list(self, *, user_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        total = await self.session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.user_id == user_id, Memory.is_active.is_(True))
        )
        records = await self.session.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.is_active.is_(True))
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return {
            "items": [serialize_memory(memory) for memory in records],
            "total": int(total or 0),
        }

    async def delete(self, *, memory_id: UUID) -> dict[str, Any]:
        memory = await self.session.get(Memory, memory_id)
        if memory is None or not memory.is_active:
            return {"deleted": False, "memory": None, "events": []}

        await asyncio.to_thread(self._client.delete, str(memory_id))

        memory.is_active = False
        event = MemoryEvent(
            memory_id=memory.id,
            event_type="DELETE",
            old_content=memory.content,
            new_content=None,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(memory)
        await self.session.refresh(event)
        await self._graph_close(str(memory.id))
        return {
            "deleted": True,
            "memory": serialize_memory(memory),
            "events": [serialize_event(event)],
        }

    async def _record_noop(self, content: str, *, reason: str) -> dict[str, Any]:
        event = MemoryEvent(event_type="NOOP", old_content=None, new_content=content)
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return {
            "memory": None,
            "events": [serialize_event(event)],
            "stored": False,
            "reason": reason,
        }

    async def _mirror_event(
        self,
        *,
        item: dict[str, Any],
        user_id: str,
        agent_id: str | None,
        run_id: str | None,
    ) -> tuple[Memory | None, MemoryEvent]:
        memory_id = _coerce_uuid(item["id"])
        content = (item.get("memory") or "").strip()
        event_type = item["event"]

        if event_type == "DELETE":
            memory = await self.session.get(Memory, memory_id)
            old_content = None
            if memory is not None:
                old_content = memory.content
                memory.is_active = False
            event = MemoryEvent(
                memory_id=memory_id if memory is not None else None,
                event_type="DELETE",
                old_content=old_content,
                new_content=None,
            )
            self.session.add(event)
            await self.session.flush()
            await self._graph_close(str(memory_id))
            return memory, event

        memory = await self.session.get(Memory, memory_id)
        old_content = None
        if memory is None:
            memory = Memory(
                id=memory_id,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                content=content,
                embedding=self.embeddings.embed(content),
                is_active=True,
            )
            self.session.add(memory)
        else:
            old_content = memory.content
            memory.content = content
            memory.embedding = self.embeddings.embed(content)
            memory.is_active = True
        await self.session.flush()

        event = MemoryEvent(
            memory_id=memory.id,
            event_type="UPDATE" if event_type == "UPDATE" else "ADD",
            old_content=old_content if event_type == "UPDATE" else None,
            new_content=content,
        )
        self.session.add(event)
        await self.session.flush()

        if event_type == "UPDATE":
            await self._graph_close(str(memory_id))
        await self._graph_upsert(memory=memory, user_id=user_id)
        return memory, event

    async def _graph_upsert(self, *, memory: Memory, user_id: str) -> None:
        fact = extract_fact(memory.content)
        if fact is None:
            return
        await self.graph.run_write(
            """
            MERGE (user:User {id: $user_id})
            MERGE (memory:Memory {id: $memory_id})
            SET memory.content = $content
            MERGE (user)-[:OWNS]->(memory)
            MERGE (source:Entity {name: $entity})
            MERGE (target:Entity {name: $object})
            CREATE (source)-[:RELATES_TO {
                user_id: $user_id,
                predicate: $predicate,
                object: $object,
                memory_id: $memory_id,
                valid_from: datetime($valid_from),
                valid_to: NULL
            }]->(target)
            """,
            {
                "user_id": user_id,
                "memory_id": str(memory.id),
                "content": memory.content,
                "entity": fact["entity"],
                "predicate": fact["predicate"],
                "object": fact["object"],
                "valid_from": memory.created_at.isoformat(),
            },
        )

    async def _graph_close(self, memory_id: str) -> None:
        await self.graph.run_write(
            """
            MATCH ()-[rel:RELATES_TO {memory_id: $memory_id}]->()
            WHERE rel.valid_to IS NULL
            SET rel.valid_to = datetime($valid_to)
            """,
            {"memory_id": memory_id, "valid_to": datetime.now(UTC).isoformat()},
        )


def _build_mem0_client() -> Any:
    """Construct a real Mem0 client, importing ``mem0ai`` and keys lazily."""

    try:
        import mem0  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only in the mem0 path
        raise RuntimeError(
            "MEMGAUGE_BACKEND=mem0 requires the 'mem0ai' package. "
            "Install it locally with `pip install mem0ai` (it is intentionally not a "
            "committed dependency so the default mock backend stays secret-free)."
        ) from exc

    api_key = os.getenv("MEM0_API_KEY")
    if api_key:
        from mem0 import MemoryClient

        return MemoryClient(api_key=api_key)

    # Open-source local Mem0 — uses OPENAI_API_KEY (or a configured provider) at runtime.
    from mem0 import Memory

    return Memory()


def _normalize_results(raw: Any) -> list[dict[str, Any]]:
    """Coerce Mem0's add/search payloads into a stable internal shape."""

    if isinstance(raw, dict):
        entries = raw.get("results", raw.get("memories", []))
    else:
        entries = raw or []

    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id") or entry.get("memory_id")
        if identifier is None:
            continue
        memory_text = entry.get("memory") or entry.get("data") or entry.get("text") or ""
        event = str(entry.get("event") or "ADD").upper()
        if event in {"NONE", "NOOP", ""}:
            event = "NONE"
        normalized.append(
            {
                "id": str(identifier),
                "memory": memory_text,
                "event": event,
                "score": entry.get("score"),
            }
        )
    return normalized


def _coerce_uuid(value: str) -> UUID:
    """Map a Mem0 identifier to a UUID, deterministically for non-UUID strings."""

    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return uuid5(NAMESPACE_URL, f"mem0:{value}")
