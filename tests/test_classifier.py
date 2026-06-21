"""Unit tests for evaluation and memory classification paths."""

from app.eval.classifier import (
    FAILURE_NONE,
    FALSE_FACT,
    RETRIEVAL_MISS,
    STALE_FACT,
    classify_case,
)
from app.memory.mock_backend import extract_fact, is_sarcastic


def test_classifier_returns_none_when_expected_memory_is_retrieved() -> None:
    assert (
        classify_case(
            expected_memory_id="mem-1",
            retrieved=[{"id": "mem-1"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids=set(),
        )
        == FAILURE_NONE
    )


def test_classifier_detects_retrieval_miss() -> None:
    assert (
        classify_case(
            expected_memory_id="mem-1",
            retrieved=[{"id": "mem-2"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids=set(),
        )
        == RETRIEVAL_MISS
    )


def test_classifier_detects_stale_and_false_fact_buckets() -> None:
    assert (
        classify_case(
            expected_memory_id="mem-2",
            retrieved=[{"id": "mem-1"}],
            inactive_memory_ids={"mem-1"},
            sarcastic_memory_ids=set(),
        )
        == STALE_FACT
    )
    assert (
        classify_case(
            expected_memory_id=None,
            retrieved=[{"id": "mem-3"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids={"mem-3"},
        )
        == FALSE_FACT
    )


def test_classifier_honors_target_failure_mode_over_default_success() -> None:
    assert (
        classify_case(
            expected_memory_id="mem-1",
            retrieved=[{"id": "mem-1"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids=set(),
            target_failure_mode=FALSE_FACT,
        )
        == FALSE_FACT
    )
    assert (
        classify_case(
            expected_memory_id="mem-1",
            retrieved=[{"id": "mem-2"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids=set(),
            target_failure_mode=STALE_FACT,
        )
        == STALE_FACT
    )
    assert (
        classify_case(
            expected_memory_id=None,
            retrieved=[],
            inactive_memory_ids=set(),
            sarcastic_memory_ids=set(),
            target_failure_mode=RETRIEVAL_MISS,
        )
        == RETRIEVAL_MISS
    )


def test_sarcastic_fact_is_detected_for_noop_storage_path() -> None:
    text = "NovaUnit likes moon dust, yeah right."

    assert extract_fact(text) == {
        "entity": "NovaUnit",
        "predicate": "likes",
        "object": "moon dust, yeah right",
    }
    assert is_sarcastic(text) is True
