# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ...observability import is_observability_enabled, span
from ..exceptions import MemorySemanticUnavailableError
from .length import estimate_token_counts_from_chars

if TYPE_CHECKING:
    from ...config.memory import SemanticConfig

DIAGNOSTIC_EMBEDDING_MODEL_ID = "diagnostic-hash-v1"


class EmbeddingProvider(Protocol):
    """Maps text to fixed-dimension vectors. Real providers are optional and
    loaded lazily by the factory; the diagnostic provider is always available.
    """

    model_id: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class _QueryEmbeddingProvider(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class _DocumentEmbeddingProvider(Protocol):
    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]: ...


class DeterministicHashEmbeddingProvider:
    """Diagnostic/test-only embedding: deterministic sha256-derived vectors.

    Stable (same text -> same vector, across runs and platforms) so the test
    suite stays fully deterministic, but it carries NO semantic meaning. Its
    hits must never be presented as real-model recall — callers surface
    ``provider="diagnostic"`` in status/envelope.
    """

    model_id = DIAGNOSTIC_EMBEDDING_MODEL_ID

    def __init__(self, *, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]:
        return self.embed(texts)

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        return estimate_token_counts_from_chars(texts)

    def max_sequence_tokens(self) -> int | None:  # codeclone: ignore[dead-code]
        return None

    def _embed_one(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{text}\x00{counter}".encode()).digest()
            for offset in range(0, len(digest), 4):
                if len(values) >= self.dimension:
                    break
                chunk = int.from_bytes(digest[offset : offset + 4], "big")
                values.append((chunk / 0xFFFFFFFF) * 2.0 - 1.0)
            counter += 1
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


def embed_query(provider: EmbeddingProvider, text: str) -> list[float]:
    with span(name="memory.embedding.query") as embed_span:
        if is_observability_enabled():
            embed_span.set_counter("chars", len(text))
        if isinstance(provider, _QueryEmbeddingProvider):
            return provider.embed_query(text)
        (vector,) = provider.embed([text])
        return vector


def embed_documents(
    provider: EmbeddingProvider,
    texts: Sequence[str],
    *,
    infer_counters: Mapping[str, int] | None = None,
) -> list[list[float]]:
    with span(name="memory.embedding.documents") as embed_span:
        if is_observability_enabled():
            embed_span.set_counter("count", len(texts))
        if isinstance(provider, _DocumentEmbeddingProvider):
            return provider.embed_documents(texts, infer_counters=infer_counters)
        return provider.embed(texts)


def _resolve_fastembed_provider(config: SemanticConfig) -> EmbeddingProvider:
    from .fastembed_provider import FastEmbedEmbeddingProvider

    model_name = config.embedding_model or "BAAI/bge-small-en-v1.5"
    return FastEmbedEmbeddingProvider(
        model_name=model_name,
        dimension=config.dimension,
        cache_dir=Path(config.embedding_cache_dir),
        allow_model_download=config.allow_model_download,
    )


def resolve_embedding_provider(config: SemanticConfig) -> EmbeddingProvider:
    """Resolve the embedding provider for the given config.

    ``diagnostic`` is always available (no deps). ``fastembed`` is the
    community local-quality provider and is loaded lazily from the optional
    ``semantic-fastembed`` extra. ``api`` is reserved for paid/cloud providers.
    """
    kind = config.embedding_provider
    if kind == "diagnostic":
        return DeterministicHashEmbeddingProvider(dimension=config.dimension)
    if kind == "fastembed":
        return _resolve_fastembed_provider(config)
    if kind == "local_model":
        raise MemorySemanticUnavailableError(
            "local_model embedding provider is not available yet; use "
            "embedding_provider='fastembed' for community local semantic search"
        )
    raise MemorySemanticUnavailableError(
        "api embedding provider is not available yet; "
        "use embedding_provider='diagnostic'"
    )


__all__ = [
    "DIAGNOSTIC_EMBEDDING_MODEL_ID",
    "DeterministicHashEmbeddingProvider",
    "EmbeddingProvider",
    "embed_documents",
    "embed_query",
    "resolve_embedding_provider",
]
