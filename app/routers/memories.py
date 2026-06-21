"""Memory API routes."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from redis.asyncio import Redis

from app.config import get_settings
from app.deps import get_memory_backend
from app.memory.base import MemoryBackend
from app.observability import get_tracer, record_operation_latency

router = APIRouter(prefix="/v1/memories", tags=["memories"])
MEMORY_BACKEND_DEPENDENCY = Depends(get_memory_backend)


class AddMemoryRequest(BaseModel):
    text: str | None = None
    messages: list[str] | None = None
    user_id: str
    agent_id: str | None = None
    run_id: str | None = None
    infer: bool = True
    sarcasm: bool = False

    @model_validator(mode="after")
    def require_text_or_messages(self) -> AddMemoryRequest:
        if not self.text and not self.messages:
            raise ValueError("Either text or messages is required")
        return self

    def joined_text(self) -> str:
        if self.text is not None:
            return self.text
        return "\n".join(self.messages or [])


class AddMemoryResponse(BaseModel):
    memory: dict[str, Any] | None
    events: list[dict[str, Any]]
    stored: bool
    reason: str | None = None
    fact: dict[str, str] | None = None


class SearchResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    cache: str = Field(default="miss")


@router.post("", response_model=AddMemoryResponse)
async def add_memory(
    payload: AddMemoryRequest,
    backend: MemoryBackend = MEMORY_BACKEND_DEPENDENCY,
) -> dict[str, Any]:
    started_at = perf_counter()
    with get_tracer().start_as_current_span("memory.add"):
        try:
            result = await backend.add(
                text=payload.joined_text(),
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                run_id=payload.run_id,
                infer=payload.infer,
                sarcasm=payload.sarcasm,
            )
            await _cache_delete_user(payload.user_id)
            return result
        finally:
            record_operation_latency("add", started_at)


@router.get("/search", response_model=SearchResponse)
async def search_memories(
    q: str,
    user_id: str,
    top_k: int = Query(default=5, ge=1, le=25),
    backend: MemoryBackend = MEMORY_BACKEND_DEPENDENCY,
) -> dict[str, Any]:
    started_at = perf_counter()
    cache_key = f"memory-search:{user_id}:{top_k}:{q}"
    with get_tracer().start_as_current_span("memory.search"):
        cached = await _cache_get(cache_key)
        if cached is not None:
            cached["cache"] = "hit"
            record_operation_latency("search", started_at)
            return cached
        try:
            result = await backend.search(q=q, user_id=user_id, top_k=top_k)
            result["cache"] = "miss"
            await _cache_set(cache_key, result)
            return result
        finally:
            record_operation_latency("search", started_at)


@router.get("")
async def list_memories(
    user_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    backend: MemoryBackend = MEMORY_BACKEND_DEPENDENCY,
) -> dict[str, Any]:
    return await backend.list(user_id=user_id, limit=limit, offset=offset)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    backend: MemoryBackend = MEMORY_BACKEND_DEPENDENCY,
) -> dict[str, Any]:
    result = await backend.delete(memory_id=memory_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="memory_not_found")
    memory = result.get("memory") or {}
    user_id = memory.get("user_id")
    if isinstance(user_id, str):
        await _cache_delete_user(user_id)
    return result


async def _cache_get(key: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        finally:
            await client.aclose()
    except Exception:
        return None


async def _cache_set(key: str, value: dict[str, Any]) -> None:
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            await client.setex(key, 60, json.dumps(value))
        finally:
            await client.aclose()
    except Exception:
        return


async def _cache_delete_user(user_id: str) -> None:
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            async for key in client.scan_iter(match=f"memory-search:{user_id}:*"):
                await client.delete(key)
        finally:
            await client.aclose()
    except Exception:
        return
