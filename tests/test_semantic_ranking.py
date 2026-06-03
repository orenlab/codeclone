# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from codeclone.memory.models import MemorySubject
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from tests.memory_fixtures import make_module_record


def _ctx(
    *, scope: tuple[str, ...] = (), symbols: tuple[str, ...] = ()
) -> RankingContext:
    return RankingContext.from_scope(
        scope_paths=scope, symbols=symbols, blast_dependents=()
    )


def test_semantic_proximity_is_additive() -> None:
    record = make_module_record("proj", "codeclone/x.py")
    base = relevance_score(record=record, subjects=[], context=_ctx(), evidence_count=0)
    boosted = relevance_score(
        record=record,
        subjects=[],
        context=_ctx(),
        evidence_count=0,
        semantic_proximity=1.0,
    )
    # Small additive weight (0.3); it re-ranks, it does not dominate.
    assert round(boosted - base, 4) == 0.3


def test_default_proximity_matches_explicit_zero() -> None:
    record = make_module_record("proj", "codeclone/x.py")
    implicit = relevance_score(
        record=record, subjects=[], context=_ctx(), evidence_count=0
    )
    explicit = relevance_score(
        record=record,
        subjects=[],
        context=_ctx(),
        evidence_count=0,
        semantic_proximity=0.0,
    )
    assert implicit == explicit


def test_scoped_shortcircuit_beats_semantic() -> None:
    # A scoped query with no contextual subject match must return 0.0 even
    # with maximal proximity: semantic cannot inject out-of-scope records.
    record = make_module_record("proj", "codeclone/x.py")
    subject = MemorySubject(
        id="s1",
        memory_id=record.id,
        subject_kind="path",
        subject_key="codeclone/unrelated.py",
    )
    score = relevance_score(
        record=record,
        subjects=[subject],
        context=_ctx(scope=("codeclone/other.py",)),
        evidence_count=0,
        semantic_proximity=1.0,
    )
    assert score == 0.0
