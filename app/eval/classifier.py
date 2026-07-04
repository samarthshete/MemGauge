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
    """Classify one case result purely from observed backend behavior.

    The failure mode is derived from what the backend actually returned versus
    the known state of the namespace — never from the case's expected label.
    ``target_failure_mode`` is accepted for signature compatibility but is NOT
    used to decide the outcome (see BUG-2 / ROADMAP R4): a case is only counted
    as a failure when the backend genuinely produced one. This keeps
    ``staleness_rate`` and ``false_fact_rate`` measures of behavior, not labels.

    Precedence (most-to-least severe observed fault):
      1. returned a fact that should never have been stored -> ``false_fact``
      2. returned a superseded/inactive fact                -> ``stale_fact``
      3. expected fact existed but was not returned          -> ``retrieval_miss``
      4. otherwise                                           -> ``none``
    """

    retrieved_ids = [str(item["id"]) for item in retrieved]
    if any(memory_id in sarcastic_memory_ids for memory_id in retrieved_ids):
        return FALSE_FACT
    if any(memory_id in inactive_memory_ids for memory_id in retrieved_ids):
        return STALE_FACT
    if expected_memory_id is not None and expected_memory_id not in retrieved_ids:
        return RETRIEVAL_MISS
    return FAILURE_NONE
