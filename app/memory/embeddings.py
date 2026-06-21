"""Embedding providers with deterministic offline fallback."""

from __future__ import annotations

import hashlib
import logging
import math
from functools import lru_cache

from app.config import get_settings

EMBEDDING_DIMENSIONS = 384
logger = logging.getLogger(__name__)


class EmbeddingProvider:
    """Embed text with fastembed, falling back to deterministic hashes offline."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: object | None = None
        self._using_fallback = False
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=model_name)
            logger.info("embedding_provider_fastembed", extra={"model": model_name})
        except Exception:
            self._using_fallback = True
            logger.info("embedding_provider_hash_fallback", extra={"model": model_name})

    def embed(self, text: str) -> list[float]:
        if not self._using_fallback and self._model is not None:
            try:
                embeddings = list(self._model.embed([text]))  # type: ignore[attr-defined]
                vector = [float(value) for value in embeddings[0]]
                if len(vector) == EMBEDDING_DIMENSIONS:
                    return _normalize(vector)
            except Exception:
                self._using_fallback = True
                logger.info("embedding_provider_hash_fallback", extra={"model": self.model_name})
        return hash_embedding(text)


def hash_embedding(text: str) -> list[float]:
    """Return a stable 384-dimensional unit vector for text."""

    normalized_text = text.strip().lower().encode("utf-8")
    values: list[float] = []
    counter = 0
    while len(values) < EMBEDDING_DIMENSIONS:
        digest = hashlib.blake2b(
            normalized_text + counter.to_bytes(4, "big"),
            digest_size=64,
        ).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == EMBEDDING_DIMENSIONS:
                break
        counter += 1
    return _normalize(values)


def _normalize(values: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude == 0:
        return values
    return [value / magnitude for value in values]


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    return EmbeddingProvider(settings.embedding_model)
