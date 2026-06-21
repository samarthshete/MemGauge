"""Unit tests for pure evaluation scoring helpers."""

from app.eval.scoring import false_fact_rate, p95, precision, recall_at_k, staleness_rate


def test_recall_at_k_counts_hits_misses_and_expected_empty_results() -> None:
    expected = ["m1", "m2", None, "m4"]
    retrieved = [["m9", "m1"], ["m3", "m2"], [], ["m5"]]

    assert recall_at_k(expected, retrieved, k=1) == 0.25
    assert recall_at_k(expected, retrieved, k=2) == 0.75


def test_failure_mode_rates_are_zero_for_empty_inputs() -> None:
    assert staleness_rate([]) == 0.0
    assert false_fact_rate([]) == 0.0
    assert precision([], []) == 0.0


def test_failure_mode_rates_count_only_matching_bucket() -> None:
    failures = ["none", "stale_fact", "false_fact", "stale_fact"]

    assert staleness_rate(failures) == 0.5
    assert false_fact_rate(failures) == 0.25


def test_p95_uses_inclusive_percentile() -> None:
    assert p95([]) == 0.0
    assert p95([42.0]) == 42.0
    assert p95([10.0, 20.0, 30.0, 40.0, 50.0]) == 48.0


def test_precision_scores_empty_expected_and_matching_retrievals() -> None:
    expected = ["m1", None, "m3", "m4"]
    retrieved = [["m1", "m2"], [], ["m9"], []]

    assert precision(expected, retrieved) == 0.375
