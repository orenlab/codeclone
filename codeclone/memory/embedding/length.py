# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ...budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    TokenEstimatorMode,
    approx_tokens_from_chars,
    estimate_texts_token_counts,
)

if TYPE_CHECKING:
    from ...config.memory import SemanticConfig

_KNOWN_EMBEDDING_MODEL_MAX_TOKENS: dict[str, int] = {
    "baai/bge-small-en-v1.5": 512,
    "baai/bge-small-en": 512,
    "baai/bge-base-en-v1.5": 512,
    "baai/bge-base-en": 512,
    "baai/bge-large-en-v1.5": 512,
}


@dataclass(frozen=True, slots=True)
class LengthDistribution:
    min: int
    p50: int
    p75: int
    p95: int
    p99: int
    max: int


@dataclass(frozen=True, slots=True)
class TokenOverflowStats:
    model_max_tokens: int | None
    over_model_limit: int
    max_overflow_tokens: int


@runtime_checkable
class TokenEstimatingProvider(Protocol):
    """Optional provider surface for batch planning and projection probes."""

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]: ...

    def max_sequence_tokens(self) -> int | None: ...


def estimate_tokens_from_chars(char_count: int) -> int:
    return approx_tokens_from_chars(char_count)


def estimate_char_counts(texts: Sequence[str]) -> tuple[int, ...]:
    return tuple(len(text) for text in texts)


def estimate_token_counts_from_chars(texts: Sequence[str]) -> tuple[int, ...]:
    return estimate_texts_token_counts(
        texts,
        estimator=TOKEN_ESTIMATOR_CHARS_APPROX,
    )


def token_overflow_stats(
    token_counts: Sequence[int],
    *,
    model_max_tokens: int | None,
) -> TokenOverflowStats:
    if model_max_tokens is None or model_max_tokens <= 0:
        return TokenOverflowStats(
            model_max_tokens=model_max_tokens,
            over_model_limit=0,
            max_overflow_tokens=0,
        )
    over = 0
    max_overflow = 0
    for count in token_counts:
        if count > model_max_tokens:
            over += 1
            max_overflow = max(max_overflow, count - model_max_tokens)
    return TokenOverflowStats(
        model_max_tokens=model_max_tokens,
        over_model_limit=over,
        max_overflow_tokens=max_overflow,
    )


def length_distribution(values: Sequence[int]) -> LengthDistribution:
    if not values:
        return LengthDistribution(min=0, p50=0, p75=0, p95=0, p99=0, max=0)
    ordered = sorted(values)
    return LengthDistribution(
        min=ordered[0],
        p50=_percentile(ordered, 50),
        p75=_percentile(ordered, 75),
        p95=_percentile(ordered, 95),
        p99=_percentile(ordered, 99),
        max=ordered[-1],
    )


def _percentile(ordered: Sequence[int], percentile: float) -> int:
    if len(ordered) == 1:
        return ordered[0]
    index = int((len(ordered) - 1) * (percentile / 100.0))
    return ordered[index]


@dataclass(frozen=True, slots=True)
class PlanningTextTokenEstimator:
    """Cheap token planning via the shared budget estimator contract."""

    mode: TokenEstimatorMode
    model_max_tokens: int | None
    encoding: str = "o200k_base"

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        return estimate_texts_token_counts(
            texts,
            encoding=self.encoding,
            estimator=self.mode,
        )

    def max_sequence_tokens(self) -> int | None:
        return self.model_max_tokens

    @property
    def estimator_label(self) -> str:
        return self.mode


def resolve_semantic_model_max_tokens(config: SemanticConfig) -> int | None:
    if config.embedding_provider == "fastembed":
        model_name = config.embedding_model or "BAAI/bge-small-en-v1.5"
        return _KNOWN_EMBEDDING_MODEL_MAX_TOKENS.get(model_name.lower(), 512)
    return None


def resolve_planning_token_estimator(
    config: SemanticConfig,
) -> PlanningTextTokenEstimator:
    return PlanningTextTokenEstimator(
        mode=config.projection_token_estimator,
        model_max_tokens=resolve_semantic_model_max_tokens(config),
    )


def resolve_token_estimator(provider: object) -> TokenEstimatingProvider:
    if isinstance(provider, TokenEstimatingProvider):
        return provider
    return PlanningTextTokenEstimator(
        mode=TOKEN_ESTIMATOR_CHARS_APPROX,
        model_max_tokens=None,
    )


def estimate_document_tokens(
    provider: object,
    texts: Sequence[str],
) -> tuple[int, ...]:
    return resolve_token_estimator(provider).estimate_token_counts(texts)


__all__ = [
    "LengthDistribution",
    "PlanningTextTokenEstimator",
    "TokenEstimatingProvider",
    "TokenOverflowStats",
    "estimate_char_counts",
    "estimate_document_tokens",
    "estimate_token_counts_from_chars",
    "estimate_tokens_from_chars",
    "length_distribution",
    "resolve_planning_token_estimator",
    "resolve_semantic_model_max_tokens",
    "resolve_token_estimator",
    "token_overflow_stats",
]
