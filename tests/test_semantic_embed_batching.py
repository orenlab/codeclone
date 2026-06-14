# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.memory.embedding.batching import (
    EmbedBatchLimits,
    pack_adaptive_batches,
    score_lengths,
)
from codeclone.memory.semantic.models import SemanticProjection
from codeclone.memory.semantic.projection import text_hash


def _projection(
    source_id: str, text: str, *, source: str = "trajectory"
) -> SemanticProjection:
    return SemanticProjection(
        source=source,  # type: ignore[arg-type]
        source_id=source_id,
        kind="test",
        text=text,
        text_hash=text_hash(text),
    )


def test_adaptive_batching_splits_on_padded_token_volume() -> None:
    short = _projection("short", "a" * 100)
    long = _projection("long", "b" * 4000)
    scored = score_lengths(
        [short, long],
        char_counts=(100, 4000),
        token_counts=(25, 1000),
        source_kinds=("trajectory", "trajectory"),
        source_ids=("short", "long"),
    )
    batches = pack_adaptive_batches(
        scored,
        limits=EmbedBatchLimits(max_documents=64, max_padded_tokens=1500),
    )
    assert len(batches) == 2
    assert {batch.items[0].source_id for batch in batches} == {"short", "long"}


def test_length_bucketing_is_deterministic() -> None:
    items = [
        _projection("b", "bb"),
        _projection("a", "aaaa"),
        _projection("c", "c"),
    ]
    scored = score_lengths(
        items,
        char_counts=(2, 4, 1),
        token_counts=(10, 20, 10),
        source_kinds=("memory", "memory", "memory"),
        source_ids=("b", "a", "c"),
    )
    assert [item.source_id for item in scored] == ["b", "c", "a"]


def test_adaptive_batching_keeps_similar_lengths_together() -> None:
    projections = [
        _projection("p1", "x" * 200),
        _projection("p2", "y" * 220),
        _projection("p3", "z" * 5000),
    ]
    scored = score_lengths(
        projections,
        char_counts=(200, 220, 5000),
        token_counts=(50, 55, 1250),
        source_kinds=("trajectory", "trajectory", "trajectory"),
        source_ids=("p1", "p2", "p3"),
    )
    batches = pack_adaptive_batches(
        scored,
        limits=EmbedBatchLimits(max_documents=64, max_padded_tokens=2000),
    )
    assert len(batches) == 2
    assert {item.source_id for item in batches[0].items} == {"p1", "p2"}
    assert batches[1].items[0].source_id == "p3"


def test_padding_amplification_metric() -> None:
    projections = [_projection("only", "x" * 400)]
    scored = score_lengths(
        projections,
        char_counts=(400,),
        token_counts=(100,),
        source_kinds=("audit",),
        source_ids=("only",),
    )
    (batch,) = pack_adaptive_batches(
        scored,
        limits=EmbedBatchLimits(max_documents=64, max_padded_tokens=8192),
    )
    assert batch.padded_tokens == batch.max_tokens
    assert batch.padding_amplification_permille == 1000
