# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Conservative chars-per-token for technical text when no tokenizer is available.
_CHARS_PER_TOKEN_HEURISTIC = 3


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
    return max(1, char_count // _CHARS_PER_TOKEN_HEURISTIC)


def estimate_char_counts(texts: Sequence[str]) -> tuple[int, ...]:
    return tuple(len(text) for text in texts)


def estimate_token_counts_from_chars(texts: Sequence[str]) -> tuple[int, ...]:
    return tuple(estimate_tokens_from_chars(len(text)) for text in texts)


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


def resolve_token_estimator(provider: object) -> TokenEstimatingProvider:
    if isinstance(provider, TokenEstimatingProvider):
        return provider
    return _CharHeuristicTokenEstimator()


@dataclass(frozen=True, slots=True)
class _CharHeuristicTokenEstimator:
    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        return estimate_token_counts_from_chars(texts)

    def max_sequence_tokens(self) -> int | None:
        return None


def estimate_document_tokens(
    provider: object,
    texts: Sequence[str],
) -> tuple[int, ...]:
    return resolve_token_estimator(provider).estimate_token_counts(texts)


__all__ = [
    "LengthDistribution",
    "TokenEstimatingProvider",
    "TokenOverflowStats",
    "estimate_char_counts",
    "estimate_document_tokens",
    "estimate_token_counts_from_chars",
    "estimate_tokens_from_chars",
    "length_distribution",
    "resolve_token_estimator",
    "token_overflow_stats",
]
