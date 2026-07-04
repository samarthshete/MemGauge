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


def test_target_failure_mode_does_not_override_observed_success() -> None:
    """BUG-2 / R4 regression: the case label must NOT stamp the outcome.

    When the backend behaves correctly (expected fact retrieved, nothing stale or
    fabricated returned), the result is ``none`` regardless of the case's
    ``target_failure_mode`` — otherwise staleness/false-fact rates measure labels,
    not behavior.
    """

    # Backend correctly returned the expected fact; a stale-labeled case must NOT
    # be counted as stale.
    assert (
        classify_case(
            expected_memory_id="mem-current",
            retrieved=[{"id": "mem-current"}],
            inactive_memory_ids={"mem-old"},
            sarcastic_memory_ids=set(),
            target_failure_mode=STALE_FACT,
        )
        == FAILURE_NONE
    )

    # Backend correctly withheld a fabrication; a false-fact-labeled case must NOT
    # be counted as a false fact just because the label says so.
    assert (
        classify_case(
            expected_memory_id=None,
            retrieved=[],
            inactive_memory_ids=set(),
            sarcastic_memory_ids={"mem-fake"},
            target_failure_mode=FALSE_FACT,
        )
        == FAILURE_NONE
    )


def test_failure_modes_are_detected_behaviorally_under_their_target_labels() -> None:
    """The same labeled cases ARE counted as failures when the backend truly fails."""

    # Stale-labeled case where the backend actually served the superseded fact.
    assert (
        classify_case(
            expected_memory_id="mem-current",
            retrieved=[{"id": "mem-old"}],
            inactive_memory_ids={"mem-old"},
            sarcastic_memory_ids=set(),
            target_failure_mode=STALE_FACT,
        )
        == STALE_FACT
    )

    # False-fact-labeled case where the backend actually returned the fabrication.
    assert (
        classify_case(
            expected_memory_id=None,
            retrieved=[{"id": "mem-fake"}],
            inactive_memory_ids=set(),
            sarcastic_memory_ids={"mem-fake"},
            target_failure_mode=FALSE_FACT,
        )
        == FALSE_FACT
    )


def test_sarcastic_fact_is_detected_for_noop_storage_path() -> None:
    text = "NovaUnit likes moon dust, yeah right."

    assert extract_fact(text) == {
        "entity": "NovaUnit",
        "predicate": "likes",
        "object": "moon dust, yeah right",
    }
    assert is_sarcastic(text) is True
