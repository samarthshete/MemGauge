"""Rule-based mock backend with real Postgres and Neo4j writes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory, MemoryEvent
from app.graph.neo4j_client import Neo4jClient
from app.memory.base import MemoryBackend
from app.memory.embeddings import EmbeddingProvider
from app.memory.retrieval import rank_memories

FACT_RE = re.compile(
    r"^\s*(?P<entity>[A-Z][A-Za-z0-9 _-]{1,60})\s+"
    r"(?P<predicate>likes|prefers|loves|hates|uses|works at|works_at|lives in|lives_in|is)\s+"
    r"(?P<object>[^.!?]+)",
    re.IGNORECASE,
)
SARCASM_MARKERS = ("/s", "sarcasm", "sarcastic", "yeah right", "as if")


class MockMemoryBackend(MemoryBackend):
    """A deterministic mock backend that persists through the real stores."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        graph: Neo4jClient,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.graph = graph
        self.embeddings = embeddings

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
        fact = extract_fact(clean_text) if infer else None
        if sarcasm or is_sarcastic(clean_text) or fact is None:
            event = MemoryEvent(event_type="NOOP", old_content=None, new_content=clean_text)
            self.session.add(event)
            await self.session.commit()
            await self.session.refresh(event)
            return {
                "memory": None,
                "events": [serialize_event(event)],
                "stored": False,
                "reason": (
                    "sarcasm_or_no_fact" if sarcasm or is_sarcastic(clean_text) else "no_fact"
                ),
            }

        embedding = self.embeddings.embed(clean_text)
        old_fact = await self._find_active_fact(user_id, fact)

        memory = Memory(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            content=clean_text,
            embedding=embedding,
        )
        self.session.add(memory)
        await self.session.flush()

        event_type = "ADD"
        old_content = None
        if old_fact is not None and old_fact["object"] != fact["object"]:
            event_type = "UPDATE"
            old_memory = await self.session.get(Memory, UUID(old_fact["memory_id"]))
            if old_memory is not None:
                old_content = old_memory.content
                old_memory.is_active = False
                old_memory.superseded_by = memory.id
            await self._close_graph_fact(old_fact["memory_id"])

        event = MemoryEvent(
            memory_id=memory.id,
            event_type=event_type,
            old_content=old_content,
            new_content=clean_text,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(memory)
        await self.session.refresh(event)

        await self._upsert_graph_fact(memory=memory, fact=fact, user_id=user_id)
        return {
            "memory": serialize_memory(memory),
            "events": [serialize_event(event)],
            "stored": True,
            "fact": fact,
        }

    async def search(self, *, q: str, user_id: str, top_k: int = 5) -> dict[str, Any]:
        top_k = max(1, min(top_k, 25))
        query_embedding = self.embeddings.embed(q)
        records = await self.session.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.is_active.is_(True))
            .order_by(Memory.created_at.desc())
            .limit(200)
        )
        candidates = [
            {
                "id": memory.id,
                "user_id": memory.user_id,
                "agent_id": memory.agent_id,
                "run_id": memory.run_id,
                "content": memory.content,
                "embedding": list(memory.embedding),
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }
            for memory in records
        ]
        graph_memory_ids = await self._graph_memory_ids_for_query(q=q, user_id=user_id)
        ranked = rank_memories(
            query=q,
            query_embedding=query_embedding,
            candidates=candidates,
            graph_memory_ids=graph_memory_ids,
            top_k=top_k,
        )
        return {
            "items": [serialize_search_result(item) for item in ranked],
            "total": len(ranked),
        }

    async def list(self, *, user_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        total = await self.session.scalar(
            select(func.count()).select_from(Memory).where(
                Memory.user_id == user_id,
                Memory.is_active.is_(True),
            )
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
        await self._close_graph_fact(str(memory.id))
        return {
            "deleted": True,
            "memory": serialize_memory(memory),
            "events": [serialize_event(event)],
        }

    async def _find_active_fact(self, user_id: str, fact: dict[str, str]) -> dict[str, Any] | None:
        records = await self.graph.run_read(
            """
            MATCH (:Entity {name: $entity})-[rel:RELATES_TO]->(:Entity)
            WHERE rel.user_id = $user_id
              AND rel.predicate = $predicate
              AND rel.valid_to IS NULL
            RETURN rel.memory_id AS memory_id, rel.object AS object
            ORDER BY rel.valid_from DESC
            LIMIT 1
            """,
            {
                "entity": fact["entity"],
                "user_id": user_id,
                "predicate": fact["predicate"],
            },
        )
        return records[0] if records else None

    async def _upsert_graph_fact(
        self,
        *,
        memory: Memory,
        fact: dict[str, str],
        user_id: str,
    ) -> None:
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

    async def _close_graph_fact(self, memory_id: str) -> None:
        await self.graph.run_write(
            """
            MATCH ()-[rel:RELATES_TO {memory_id: $memory_id}]->()
            WHERE rel.valid_to IS NULL
            SET rel.valid_to = datetime($valid_to)
            """,
            {"memory_id": memory_id, "valid_to": datetime.now(UTC).isoformat()},
        )

    async def _graph_memory_ids_for_query(self, *, q: str, user_id: str) -> set[UUID]:
        entities = extract_query_entities(q)
        if not entities:
            return set()
        records = await self.graph.run_read(
            """
            MATCH (source:Entity)-[rel:RELATES_TO]->(:Entity)
            WHERE rel.user_id = $user_id
              AND rel.valid_to IS NULL
              AND toLower(source.name) IN $entities
            RETURN rel.memory_id AS memory_id
            """,
            {"user_id": user_id, "entities": entities},
        )
        return {UUID(record["memory_id"]) for record in records}


def extract_fact(text: str) -> dict[str, str] | None:
    match = FACT_RE.match(text)
    if match is None:
        return None
    predicate = match.group("predicate").strip().lower().replace(" ", "_")
    return {
        "entity": normalize_entity(match.group("entity")),
        "predicate": predicate,
        "object": normalize_entity(match.group("object")),
    }


def extract_query_entities(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][A-Za-z0-9_-]{1,60}\b", text)
    return [normalize_entity(match).lower() for match in matches]


def normalize_entity(value: str) -> str:
    return " ".join(value.strip(" .!?;:,").split())


def is_sarcastic(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SARCASM_MARKERS)


def serialize_memory(memory: Memory) -> dict[str, Any]:
    return {
        "id": str(memory.id),
        "user_id": memory.user_id,
        "agent_id": memory.agent_id,
        "run_id": memory.run_id,
        "content": memory.content,
        "is_active": memory.is_active,
        "superseded_by": str(memory.superseded_by) if memory.superseded_by else None,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
    }


def serialize_event(event: MemoryEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "memory_id": str(event.memory_id) if event.memory_id else None,
        "event_type": event.event_type,
        "old_content": event.old_content,
        "new_content": event.new_content,
        "created_at": event.created_at.isoformat(),
    }


def serialize_search_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item["id"]),
        "user_id": item["user_id"],
        "agent_id": item["agent_id"],
        "run_id": item["run_id"],
        "content": item["content"],
        "score": item["score"],
        "signals": item["signals"],
        "created_at": item["created_at"].isoformat(),
        "updated_at": item["updated_at"].isoformat(),
    }
