# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .coverage import ScopeCoverageReport, compute_scope_coverage, coverage_delta
from .ingest.receipts import propose_memory_from_changed_paths
from .models import MemoryProject
from .sqlite_store import SqliteEngineeringMemoryStore
from .staleness import StalenessReport, apply_scope_staleness


@dataclass(frozen=True, slots=True)
class FinishMemoryWorkflowResult:
    candidates: list[dict[str, object]]
    staleness: StalenessReport
    coverage_before: ScopeCoverageReport
    coverage_after: ScopeCoverageReport
    coverage_delta: dict[str, object]


def execute_finish_memory_workflow(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    changed_paths: Sequence[str],
    claims_text: str | None,
    review_text: str | None,
    verification_profile: str | None,
    max_candidates: int,
    max_statement_chars: int,
    attested_evidence: Mapping[str, object] | None = None,
) -> FinishMemoryWorkflowResult:
    """Run the transport-neutral propose-on-finish memory workflow.

    ``attested_evidence`` carries the finished change's attested identifiers
    (receipt digest, patch-trail digest, commit sha, run id). When provided it is
    threaded down so proposed candidates carry durable evidence rows instead of a
    bare stub. The controller populates it from the finish result.
    """
    before = compute_scope_coverage(
        store,
        project_id=project.id,
        scope_paths=changed_paths,
    )
    candidates = propose_memory_from_changed_paths(
        store,
        project=project,
        changed_paths=changed_paths,
        claims_text=claims_text,
        review_text=review_text,
        verification_profile=verification_profile,
        max_candidates=max_candidates,
        max_statement_chars=max_statement_chars,
        attested_evidence=attested_evidence,
    )
    staleness = apply_scope_staleness(
        store,
        project_id=project.id,
        changed_paths=changed_paths,
    )
    after = compute_scope_coverage(
        store,
        project_id=project.id,
        scope_paths=changed_paths,
    )
    delta = coverage_delta(before, after)
    return FinishMemoryWorkflowResult(
        candidates=candidates,
        staleness=staleness,
        coverage_before=before,
        coverage_after=after,
        coverage_delta=delta,
    )


__all__ = ["FinishMemoryWorkflowResult", "execute_finish_memory_workflow"]
