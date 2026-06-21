"""Unit tests for embedding provider fallback behavior."""

import math
import sys

from app.memory.embeddings import EMBEDDING_DIMENSIONS, EmbeddingProvider, hash_embedding


def test_hash_embedding_is_deterministic_unit_vector() -> None:
    first = hash_embedding("Alpha likes tea")
    second = hash_embedding(" alpha likes tea ")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_embedding_provider_falls_back_when_model_import_is_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fastembed", None)

    provider = EmbeddingProvider("missing-test-model")
    vector = provider.embed("offline fallback text")

    assert vector == hash_embedding("offline fallback text")
    assert len(vector) == EMBEDDING_DIMENSIONS
