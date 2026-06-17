# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class EmbedBatchLimits:
    """Adaptive embed batch contract: document count and padded token volume."""

    max_documents: int = 64
    max_padded_tokens: int = 8192


@dataclass(frozen=True, slots=True)
class LengthScoredItem(Generic[T]):
    item: T
    char_count: int
    token_count: int
    source_kind: str
    source_id: str


@dataclass(frozen=True, slots=True)
class EmbedBatchPlan(Generic[T]):
    """One adaptive inference batch with padding telemetry."""

    items: tuple[LengthScoredItem[T], ...]
    total_chars: int
    max_chars: int
    total_tokens: int
    max_tokens: int
    padded_tokens: int
    padding_amplification_permille: int


def length_sort_key(item: LengthScoredItem[T]) -> tuple[int, str, str]:
    return (item.token_count, item.source_kind, item.source_id)


def score_lengths(
    items: Sequence[T],
    *,
    char_counts: Sequence[int],
    token_counts: Sequence[int],
    source_kinds: Sequence[str],
    source_ids: Sequence[str],
) -> tuple[LengthScoredItem[T], ...]:
    if not (
        len(items)
        == len(char_counts)
        == len(token_counts)
        == len(source_kinds)
        == len(source_ids)
    ):
        raise ValueError("length score inputs must align with items")
    scored = [
        LengthScoredItem(
            item=item,
            char_count=char_count,
            token_count=token_count,
            source_kind=source_kind,
            source_id=source_id,
        )
        for item, char_count, token_count, source_kind, source_id in zip(
            items,
            char_counts,
            token_counts,
            source_kinds,
            source_ids,
            strict=True,
        )
    ]
    return tuple(sorted(scored, key=length_sort_key))


def pack_adaptive_batches(
    scored_items: Sequence[LengthScoredItem[T]],
    *,
    limits: EmbedBatchLimits,
) -> list[EmbedBatchPlan[T]]:
    if limits.max_documents <= 0 or limits.max_padded_tokens <= 0:
        raise ValueError("embed batch limits must be positive")
    if not scored_items:
        return []
    batches: list[list[LengthScoredItem[T]]] = []
    current: list[LengthScoredItem[T]] = []
    current_max_tokens = 0

    for item in scored_items:
        next_size = len(current) + 1
        next_max_tokens = max(current_max_tokens, item.token_count)
        padded = next_size * next_max_tokens
        if current and (
            next_size > limits.max_documents or padded > limits.max_padded_tokens
        ):
            batches.append(current)
            current = [item]
            current_max_tokens = item.token_count
        else:
            current.append(item)
            current_max_tokens = next_max_tokens
    if current:
        batches.append(current)
    return [_plan_batch(batch) for batch in batches]


def _plan_batch(batch: Sequence[LengthScoredItem[T]]) -> EmbedBatchPlan[T]:
    char_counts = [item.char_count for item in batch]
    token_counts = [item.token_count for item in batch]
    total_tokens = sum(token_counts)
    max_tokens = max(token_counts)
    padded_tokens = len(batch) * max_tokens
    amplification = (
        round((padded_tokens * 1000) / total_tokens) if total_tokens else 1000
    )
    return EmbedBatchPlan(
        items=tuple(batch),
        total_chars=sum(char_counts),
        max_chars=max(char_counts),
        total_tokens=total_tokens,
        max_tokens=max_tokens,
        padded_tokens=padded_tokens,
        padding_amplification_permille=int(amplification),
    )


__all__ = [
    "EmbedBatchLimits",
    "EmbedBatchPlan",
    "LengthScoredItem",
    "length_sort_key",
    "pack_adaptive_batches",
    "score_lengths",
]
