"""Hybrid memory retrieval scoring."""

from __future__ import annotations

import math
import re
from typing import Any
from uuid import UUID

VECTOR_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.2
GRAPH_WEIGHT = 0.2

TOKEN_RE = re.compile(r"[a-z0-9]+")


def rank_memories(
    *,
    query: str,
    query_embedding: list[float],
    candidates: list[dict[str, Any]],
    graph_memory_ids: set[UUID],
    top_k: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        memory_id = candidate["id"]
        signals = {
            "vector": float(cosine_similarity_01(query_embedding, candidate["embedding"])),
            "keyword": float(keyword_score(query, candidate["content"])),
            "graph": 1.0 if memory_id in graph_memory_ids else 0.0,
        }
        score = float(
            VECTOR_WEIGHT * signals["vector"]
            + KEYWORD_WEIGHT * signals["keyword"]
            + GRAPH_WEIGHT * signals["graph"]
        )
        ranked.append(
            {
                **candidate,
                "score": round(score, 6),
                "signals": {key: round(value, 6) for key, value in signals.items()},
            }
        )
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:top_k]


def cosine_similarity_01(left: list[float], right: list[float]) -> float:
    dot = sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=False)
    )
    left_mag = math.sqrt(sum(value * value for value in left))
    right_mag = math.sqrt(sum(value * value for value in right))
    if left_mag == 0 or right_mag == 0:
        return 0.0
    cosine = dot / (left_mag * right_mag)
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def keyword_score(query: str, content: str) -> float:
    query_tokens = set(TOKEN_RE.findall(query.lower()))
    content_tokens = set(TOKEN_RE.findall(content.lower()))
    if not query_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)
