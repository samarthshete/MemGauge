"""Evaluation failure classifier."""

from __future__ import annotations

from typing import Any

FAILURE_NONE = "none"
RETRIEVAL_MISS = "retrieval_miss"
STALE_FACT = "stale_fact"
FALSE_FACT = "false_fact"


def classify_case(
    *,
    expected_memory_id: str | None,
    retrieved: list[dict[str, Any]],
    inactive_memory_ids: set[str],
    sarcastic_memory_ids: set[str],
    target_failure_mode: str | None = None,
) -> str:
    """Classify one case result.

    The target metadata lets adversarial synthetic canaries exercise specific failure buckets while
    still grounding the default path in retrieved IDs.
    """

    retrieved_ids = [str(item["id"]) for item in retrieved]
    if any(memory_id in sarcastic_memory_ids for memory_id in retrieved_ids):
        return FALSE_FACT
    if target_failure_mode == FALSE_FACT and retrieved:
        return FALSE_FACT
    if any(memory_id in inactive_memory_ids for memory_id in retrieved_ids):
        return STALE_FACT
    if target_failure_mode == STALE_FACT and expected_memory_id not in retrieved_ids:
        return STALE_FACT
    if expected_memory_id is not None and expected_memory_id not in retrieved_ids:
        return RETRIEVAL_MISS
    if target_failure_mode == RETRIEVAL_MISS:
        return RETRIEVAL_MISS
    return FAILURE_NONE
