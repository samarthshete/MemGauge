"""Pure evaluation scoring helpers."""

from __future__ import annotations

from statistics import quantiles


def recall_at_k(expected_ids: list[str | None], retrieved_ids: list[list[str]], k: int) -> float:
    if not expected_ids:
        return 0.0
    hits = 0
    for expected_id, retrieved in zip(expected_ids, retrieved_ids, strict=False):
        if expected_id is None:
            hits += 1 if not retrieved[:k] else 0
        elif expected_id in retrieved[:k]:
            hits += 1
    return hits / len(expected_ids)


def precision(expected_ids: list[str | None], retrieved_ids: list[list[str]]) -> float:
    if not expected_ids:
        return 0.0
    scores: list[float] = []
    for expected_id, retrieved in zip(expected_ids, retrieved_ids, strict=False):
        if not retrieved:
            scores.append(1.0 if expected_id is None else 0.0)
        elif expected_id is None:
            scores.append(0.0)
        else:
            scores.append(1.0 / len(retrieved) if expected_id in retrieved else 0.0)
    return sum(scores) / len(scores)


def staleness_rate(failure_modes: list[str]) -> float:
    return _rate(failure_modes, "stale_fact")


def false_fact_rate(failure_modes: list[str]) -> float:
    return _rate(failure_modes, "false_fact")


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=20, method="inclusive")[18]


def _rate(values: list[str], target: str) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value == target) / len(values)
