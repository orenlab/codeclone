# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.memory.semantic.chunking import (
    IdentityPassageChunker,
    collapse_trajectory_hits,
    expand_projection,
    trajectory_chunk_row_id,
)
from codeclone.memory.semantic.models import SemanticHit, SemanticProjection
from codeclone.memory.semantic.projection import text_hash


class _FixedChunker:
    def __init__(self, chunks: tuple[str, ...]) -> None:
        self._chunks = chunks

    def chunk_text(self, text: str) -> tuple[str, ...]:
        return self._chunks


def _trajectory_projection(
    text: str, *, source_id: str = "traj-1"
) -> SemanticProjection:
    return SemanticProjection(
        source="trajectory",
        source_id=source_id,
        kind="trajectory",
        text=text,
        text_hash=text_hash(text),
    )


def _memory_projection(text: str) -> SemanticProjection:
    return SemanticProjection(
        source="memory",
        source_id="mem-1",
        kind="contract_note",
        text=text,
        text_hash=text_hash(text),
    )


def test_trajectory_chunk_row_id_is_deterministic() -> None:
    assert trajectory_chunk_row_id("abc", 0) == "trajectory:abc:chunk:000"
    assert trajectory_chunk_row_id("abc", 12) == "trajectory:abc:chunk:012"


def test_expand_projection_keeps_memory_as_single_row() -> None:
    projection = _memory_projection("short note")
    (unit,) = expand_projection(projection, IdentityPassageChunker())
    assert unit.row_id == "mem-1"
    assert unit.parent_id is None
    assert unit.chunk_index is None


def test_expand_projection_splits_trajectory_into_chunk_rows() -> None:
    projection = _trajectory_projection("full trajectory text")
    chunker = _FixedChunker(("part-a", "part-b", "part-c"))
    units = expand_projection(projection, chunker)
    assert len(units) == 3
    assert [unit.row_id for unit in units] == [
        "trajectory:traj-1:chunk:000",
        "trajectory:traj-1:chunk:001",
        "trajectory:traj-1:chunk:002",
    ]
    assert all(unit.parent_id == "traj-1" for unit in units)
    assert [unit.chunk_index for unit in units] == [0, 1, 2]
    assert all(unit.chunk_count == 3 for unit in units)
    assert [unit.text_hash for unit in units] == [
        text_hash("part-a"),
        text_hash("part-b"),
        text_hash("part-c"),
    ]


def test_expand_projection_single_trajectory_chunk_uses_parent_row_id() -> None:
    projection = _trajectory_projection("fits in one chunk")
    (unit,) = expand_projection(projection, IdentityPassageChunker())
    assert unit.row_id == "traj-1"
    assert unit.parent_id is None


def test_collapse_trajectory_hits_keeps_best_score_per_parent() -> None:
    hits = [
        SemanticHit(
            source_id="trajectory:t1:chunk:000",
            source="trajectory",
            score=0.4,
            parent_id="t1",
            chunk_index=0,
            chunk_count=3,
        ),
        SemanticHit(
            source_id="trajectory:t1:chunk:001",
            source="trajectory",
            score=0.9,
            parent_id="t1",
            chunk_index=1,
            chunk_count=3,
        ),
        SemanticHit(
            source_id="trajectory:t2:chunk:000",
            source="trajectory",
            score=0.7,
            parent_id="t2",
            chunk_index=0,
            chunk_count=1,
        ),
    ]
    collapsed = collapse_trajectory_hits(hits, k=2)
    assert len(collapsed) == 2
    assert collapsed[0].parent_id == "t1"
    assert collapsed[0].chunk_index == 1
    assert collapsed[0].score == 0.9
    assert collapsed[1].parent_id == "t2"


def test_chunking_public_exports() -> None:
    from codeclone.memory.semantic import chunking as chunking_mod

    assert chunking_mod.TRAJECTORY_SEARCH_OVERSAMPLE == 4
