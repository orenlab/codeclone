# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from codeclone.config.memory import SemanticConfig
from codeclone.memory.embedding import (
    DeterministicHashEmbeddingProvider,
    embed_documents,
    embed_query,
    resolve_embedding_provider,
)
from codeclone.memory.exceptions import MemorySemanticUnavailableError


class _FakeTextEmbedding:
    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: str,
        local_files_only: bool,
        vector_value: float = 1.0,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only
        self.vector_value = vector_value
        self.inputs: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [[self.vector_value] * 384 for _ in texts]


def _install_fake_fastembed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vector_value: float = 1.0,
) -> list[_FakeTextEmbedding]:
    import importlib

    created: list[_FakeTextEmbedding] = []
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None) -> Any:
        if name != "fastembed":
            return original_import_module(name, package)

        class _ConfiguredFakeTextEmbedding(_FakeTextEmbedding):
            def __init__(
                self,
                *,
                model_name: str,
                cache_dir: str,
                local_files_only: bool,
            ) -> None:
                super().__init__(
                    model_name=model_name,
                    cache_dir=cache_dir,
                    local_files_only=local_files_only,
                    vector_value=vector_value,
                )
                created.append(self)

        return SimpleNamespace(TextEmbedding=_ConfiguredFakeTextEmbedding)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)
    return created


def test_deterministic_embedding_is_stable_and_correct_dimension() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=64)
    first = provider.embed(["recover after MCP restart"])
    second = provider.embed(["recover after MCP restart"])
    assert first == second  # same text -> same vector
    assert len(first) == 1
    assert len(first[0]) == 64


def test_deterministic_embedding_is_l2_normalized() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=128)
    (vector,) = provider.embed(["checkpoint degrades to scope_only"])
    norm = math.sqrt(sum(value * value for value in vector))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_deterministic_embedding_distinguishes_texts() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=64)
    vectors = provider.embed(["alpha", "beta"])
    assert vectors[0] != vectors[1]


def test_deterministic_embedding_rejects_nonpositive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        DeterministicHashEmbeddingProvider(dimension=0)


def test_resolve_diagnostic_provider() -> None:
    config = SemanticConfig(embedding_provider="diagnostic", dimension=256)
    provider = resolve_embedding_provider(config)
    assert provider.model_id == "diagnostic-hash-v1"
    assert provider.dimension == 256


def test_resolve_local_model_provider_fails_clear() -> None:
    config = SemanticConfig(embedding_provider="local_model")
    with pytest.raises(MemorySemanticUnavailableError, match="local_model"):
        resolve_embedding_provider(config)


def test_resolve_api_provider_fails_clear() -> None:
    config = SemanticConfig(embedding_provider="api")
    with pytest.raises(MemorySemanticUnavailableError, match="api"):
        resolve_embedding_provider(config)


def test_fastembed_provider_uses_local_model_cache_and_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fake_fastembed(monkeypatch)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    assert provider.model_id == "fastembed:BAAI/bge-small-en-v1.5"
    assert provider.dimension == 384
    assert embed_query(provider, "recover after restart") == [1.0] * 384
    assert embed_documents(provider, ["scope-aware hygiene"]) == [[1.0] * 384]
    assert created[0].local_files_only is True
    assert created[0].inputs == [
        "query: recover after restart",
        "passage: scope-aware hygiene",
    ]


def test_fastembed_provider_honors_download_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fake_fastembed(monkeypatch, vector_value=0.0)
    config = SemanticConfig(
        embedding_provider="fastembed",
        allow_model_download=True,
    )
    provider = resolve_embedding_provider(config)

    assert provider.dimension == 384
    assert [item.local_files_only for item in created] == [False]


def test_fastembed_provider_fails_clear_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None) -> Any:
        if name == "fastembed":
            raise ImportError(name)
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    config = SemanticConfig(embedding_provider="fastembed")
    with pytest.raises(MemorySemanticUnavailableError, match="semantic-fastembed"):
        resolve_embedding_provider(config)
