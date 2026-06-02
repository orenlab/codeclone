# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import math

import pytest

from codeclone.config.memory import SemanticConfig
from codeclone.memory.embedding import (
    DeterministicHashEmbeddingProvider,
    resolve_embedding_provider,
)
from codeclone.memory.exceptions import MemorySemanticUnavailableError


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
