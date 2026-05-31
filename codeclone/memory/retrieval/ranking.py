# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import MemoryRecord, MemorySubject
from ..paths import expand_scope_paths, subject_matches_scope

_TYPE_BOOST: dict[str, float] = {
    "contract_note": 0.25,
    "document_link": 0.2,
    "public_surface": 0.15,
    "risk_note": 0.15,
    "test_anchor": 0.15,
    "contradiction_note": 0.1,
    "module_role": 0.1,
}
_INGEST_BOOST: dict[str, float] = {
    "git": 0.1,
    "contract": 0.08,
    "doc": 0.06,
    "test": 0.05,
    "analysis": 0.04,
}


@dataclass(frozen=True, slots=True)
class RankingContext:
    scope_paths: frozenset[str]
    symbols: frozenset[str]
    blast_dependents: frozenset[str]

    @classmethod
    def from_scope(
        cls,
        *,
        scope_paths: Sequence[str],
        symbols: Sequence[str],
        blast_dependents: Sequence[str],
    ) -> RankingContext:
        normalized_scope = frozenset(scope_paths)
        return cls(
            scope_paths=expand_scope_paths(normalized_scope),
            symbols=frozenset(symbols),
            blast_dependents=frozenset(blast_dependents),
        )


def relevance_score(
    *,
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
    context: RankingContext,
    evidence_count: int,
) -> float:
    scoped = bool(context.scope_paths or context.symbols)
    score = 0.0
    has_contextual_match = False
    for subject in subjects:
        key = subject.subject_key.replace("\\", "/").strip("/")
        boost = 0.0
        if key in context.symbols:
            boost = 1.0
        else:
            scope_boost = subject_matches_scope(key, scope_paths=context.scope_paths)
            if scope_boost > 0.0:
                boost = scope_boost
            elif key in context.blast_dependents:
                boost = 0.7
        if boost > 0.0:
            score += boost
            has_contextual_match = True

    if scoped and not has_contextual_match:
        return 0.0

    score += _TYPE_BOOST.get(record.type, 0.0)
    score += _INGEST_BOOST.get(record.ingest_source, 0.0)
    if record.confidence == "verified":
        score += 0.15
    elif record.confidence == "supported":
        score += 0.1
    if record.approved_by:
        score += 0.1
    if evidence_count > 0:
        score += min(0.1, evidence_count * 0.02)
    if record.status == "stale":
        score -= 0.5
    return round(score, 4)


__all__ = ["RankingContext", "relevance_score"]
