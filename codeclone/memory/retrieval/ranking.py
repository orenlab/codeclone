# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import MemoryRecord, MemorySubject

_CONTRACT_TYPES = frozenset({"contract_note", "public_surface"})
_TYPE_BOOST: dict[str, float] = {
    "contract_note": 0.8,
    "document_link": 0.65,
    "public_surface": 0.55,
    "risk_note": 0.5,
    "test_anchor": 0.45,
    "contradiction_note": 0.4,
    "module_role": 0.15,
}
_INGEST_BOOST: dict[str, float] = {
    "git": 0.35,
    "contract": 0.3,
    "doc": 0.25,
    "test": 0.2,
    "analysis": 0.1,
}


def _prefix_scope_boost(key: str, scope_paths: frozenset[str]) -> float:
    for scope_path in scope_paths:
        if key == scope_path or key.startswith(f"{scope_path}/"):
            return 0.9
        if scope_path.startswith((key, f"{key}/")):
            return 0.8
    return 0.0


def _subject_context_boost(
    key: str,
    context: RankingContext,
) -> tuple[float, bool]:
    """Return relevance boost and whether blast-dependent scoring should be skipped."""
    boost = 0.0
    if key in context.symbols:
        boost += 1.0
    if key in context.scope_paths:
        boost += 1.0
        return boost, True
    boost += _prefix_scope_boost(key, context.scope_paths)
    return boost, False


@dataclass(frozen=True, slots=True)
class RankingContext:
    scope_paths: frozenset[str]
    symbols: frozenset[str]
    blast_dependents: frozenset[str]


def relevance_score(
    *,
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
    context: RankingContext,
    evidence_count: int,
) -> float:
    score = 0.0
    for subject in subjects:
        key = subject.subject_key.replace("\\", "/").strip("/")
        subject_boost, skip_blast = _subject_context_boost(key, context)
        score += subject_boost
        if not skip_blast and key in context.blast_dependents:
            score += 0.7

    if record.type in _CONTRACT_TYPES:
        score += 0.6
    score += _TYPE_BOOST.get(record.type, 0.0)
    score += _INGEST_BOOST.get(record.ingest_source, 0.0)
    if record.confidence == "verified":
        score += 0.3
    elif record.confidence == "supported":
        score += 0.2
    if record.approved_by:
        score += 0.2
    if evidence_count > 0:
        score += min(0.2, evidence_count * 0.05)
    if record.status == "stale":
        score -= 0.5
    return round(score, 4)


__all__ = ["RankingContext", "relevance_score"]
