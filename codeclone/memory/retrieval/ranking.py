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
        if key in context.symbols:
            score += 1.0
        if key in context.scope_paths:
            score += 1.0
            continue
        for scope_path in context.scope_paths:
            if key == scope_path or key.startswith(f"{scope_path}/"):
                score += 0.9
                break
            if scope_path.startswith((key, f"{key}/")):
                score += 0.8
                break
        if key in context.blast_dependents:
            score += 0.7

    if record.type in _CONTRACT_TYPES:
        score += 0.6
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
