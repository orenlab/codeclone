# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from ...observability import is_observability_enabled, span
from ..exceptions import MemorySemanticUnavailableError
from .length import estimate_token_counts_from_chars

_KNOWN_MODEL_MAX_TOKENS: dict[str, int] = {
    "baai/bge-small-en-v1.5": 512,
    "baai/bge-small-en": 512,
    "baai/bge-base-en-v1.5": 512,
    "baai/bge-base-en": 512,
    "baai/bge-large-en-v1.5": 512,
}


class _TextEmbeddingModel(Protocol):
    model: object

    def embed(self, texts: list[str]) -> Iterable[object]: ...


class _TokenizingTextModel(Protocol):
    tokenizer: object | None

    def tokenize(self, documents: list[str]) -> list[object]: ...


class FastEmbedEmbeddingProvider:
    """Local FastEmbed provider for semantic-quality community retrieval.

    FastEmbed remains an optional dependency. The provider runs local ONNX
    embeddings and uses explicit query/passage prefixes for retrieval models
    such as BAAI/bge-small-en-v1.5. Model download is disabled by default; users
    must opt in or pre-populate the cache.
    """

    def __init__(
        self,
        *,
        model_name: str,
        dimension: int,
        cache_dir: Path,
        allow_model_download: bool,
    ) -> None:
        self.model_name = model_name
        self.model_id = f"fastembed:{model_name}"
        self.dimension = dimension
        self.cache_dir = cache_dir
        self.allow_model_download = allow_model_download
        # Verify the optional package eagerly (cheap) so "extra not installed"
        # still fails at construction, but defer the expensive ONNX model load
        # (~hundreds of MB / seconds) to the first embed. A provider that is
        # built but never embeds — e.g. a semantic query against an index that
        # turns out to be unavailable — then costs nothing. Callers degrade
        # gracefully when the model is unavailable at embed time.
        self._text_embedding = self._resolve_text_embedding()
        self._model: _TextEmbeddingModel | None = None

    def _resolve_text_embedding(self) -> Callable[..., object]:
        try:
            fastembed = importlib.import_module("fastembed")
        except ImportError as exc:
            raise MemorySemanticUnavailableError(
                "fastembed embedding provider requires the optional "
                "`codeclone[semantic-fastembed]` extra"
            ) from exc
        text_embedding = getattr(fastembed, "TextEmbedding", None)
        if text_embedding is None:
            raise MemorySemanticUnavailableError(
                "fastembed package does not expose TextEmbedding"
            )
        return cast("Callable[..., object]", text_embedding)

    def _get_model(self) -> _TextEmbeddingModel:
        if self._model is not None:
            return self._model
        with span(name="memory.embedding.model_load"):
            try:
                model = self._text_embedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir),
                    local_files_only=not self.allow_model_download,
                )
            except Exception as exc:
                mode = (
                    "download disabled"
                    if not self.allow_model_download
                    else "download allowed"
                )
                raise MemorySemanticUnavailableError(
                    "fastembed embedding model is unavailable "
                    f"({self.model_name}; {mode}; cache={self.cache_dir}): {exc}"
                ) from exc
            self._model = cast(_TextEmbeddingModel, model)
        return self._model

    def _inner_text_model(self) -> _TokenizingTextModel:
        return cast(_TokenizingTextModel, self._get_model().model)

    def max_sequence_tokens(self) -> int | None:
        inner = self._inner_text_model()
        tokenizer = inner.tokenizer
        if tokenizer is not None:
            truncation = getattr(tokenizer, "truncation", None)
            if truncation is not None:
                max_length = getattr(truncation, "max_length", None)
                if isinstance(max_length, int) and max_length > 0:
                    return max_length
        return _KNOWN_MODEL_MAX_TOKENS.get(self.model_name.lower(), 512)

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        prefixed = [f"passage: {text}" for text in texts]
        inner = self._inner_text_model()
        tokenize = getattr(inner, "tokenize", None)
        if tokenize is None:
            return estimate_token_counts_from_chars(prefixed)
        encodings = tokenize(prefixed)
        return tuple(len(getattr(encoding, "ids", ())) for encoding in encodings)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        (vector,) = self._embed_prefixed([f"query: {text}"])
        return vector

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]:
        return self._embed_prefixed(
            [f"passage: {text}" for text in texts],
            infer_counters=infer_counters,
        )

    def _embed_prefixed(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]:
        with span(name="memory.embedding.infer") as infer_span:
            if is_observability_enabled():
                infer_span.set_counter("batch", len(texts))
                if infer_counters is not None:
                    for key, value in sorted(infer_counters.items()):
                        infer_span.set_counter(key, value)
            try:
                raw_vectors = list(self._get_model().embed(list(texts)))
            except Exception as exc:
                raise MemorySemanticUnavailableError(
                    f"fastembed embedding failed for model {self.model_name}: {exc}"
                ) from exc
            vectors = [self._coerce_vector(vector) for vector in raw_vectors]
            for vector in vectors:
                if len(vector) != self.dimension:
                    raise MemorySemanticUnavailableError(
                        "fastembed embedding dimension mismatch: "
                        f"expected {self.dimension}, got {len(vector)} for "
                        f"{self.model_name}"
                    )
            return vectors

    @staticmethod
    def _coerce_vector(raw_vector: object) -> list[float]:
        if not isinstance(raw_vector, Iterable) or isinstance(raw_vector, str):
            raise MemorySemanticUnavailableError(
                "fastembed returned a non-iterable embedding vector"
            )
        return [float(value) for value in raw_vector]


__all__ = ["FastEmbedEmbeddingProvider"]
