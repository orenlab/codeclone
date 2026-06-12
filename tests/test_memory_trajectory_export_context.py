# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from codeclone.audit.events import (
    EVENT_CLAIM_COMPLETED,
    AuditEvent,
    event_core_for_event,
)
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.models import MemoryEvidence, generate_memory_id
from codeclone.memory.trajectory.export import export_trajectories_jsonl
from codeclone.memory.trajectory.export_context import select_canonical_trajectories
from codeclone.memory.trajectory.models import TRAJECTORY_PROJECTION_VERSION_V1
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    memory_store,
    seed_path_subject_record,
    seed_trajectory_audit_workflow,
)


def test_claim_event_core_includes_bounded_citations() -> None:
    core = event_core_for_event(
        AuditEvent(
            event_type=EVENT_CLAIM_COMPLETED,
            severity="info",
            repo_root_digest="digest",
            agent_pid=1,
            agent_label="agent",
            status="valid",
            payload={
                "valid": True,
                "citations_found": 1,
                "violations": [],
                "warnings": [],
                "validated_citations": [
                    {"cited_id": "finding-abc", "kind": "finding", "valid": True}
                ],
            },
        )
    )
    facts = core["facts"]
    assert isinstance(facts, dict)
    citations = facts.get("citations")
    assert isinstance(citations, list)
    assert citations[0]["cited_id"] == "finding-abc"


def test_select_canonical_trajectories_prefers_newer_projection_version(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        current = projection.trajectories[0]
        legacy = replace(
            current,
            id="traj-legacy-test-id",
            projection_version=TRAJECTORY_PROJECTION_VERSION_V1,
            trajectory_digest="legacy-digest",
        )
        selected = select_canonical_trajectories([legacy, current])
        assert len(selected) == 1
        assert selected[0].projection_version == current.projection_version


def test_export_record_includes_context_citations_and_patch_trail(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(
            root=root,
            audit_db=audit_db,
            scope_path="pkg/service.py",
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = store.list_canonical_trajectories_for_export(
            project_id=project.id
        )[0]
        record = seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/service.py",
            statement="active memory for export context",
        )
        store.write_evidence(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=record.id,
                evidence_kind="trajectory",
                ref=trajectory.id,
                locator=None,
                quote=None,
                digest=trajectory.trajectory_digest,
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()
        config = resolve_memory_config(root)
        enabled = replace(config, trajectory_export_enabled=True)
        out = tmp_path / "export.jsonl"
        result = export_trajectories_jsonl(
            store=store,
            project=project,
            root_path=root,
            config=enabled,
            profile_name="agent-change-control-v1",
            output_path=out,
        )
        payload = json.loads(out.read_text(encoding="utf-8").strip())
        assert payload["schema_version"] == "2"
        assert "pkg/service.py" in payload["task"]["scope"]["paths"]
        assert payload["context"]["memory_precedents"]
        assert payload["context"]["memory_precedents"][0]["memory_id"] == record.id
        assert "patch_trail_summary" in payload
        assert result.manifest["deduplicated_workflows"] == 1


def test_export_context_helper_rejection_and_deduplication_edges(
    tmp_path: Path,
) -> None:
    from codeclone.memory.trajectory import export_context

    assert export_context.projection_version_rank("trajectory-vnext") == 0

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        current = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]

    legacy = replace(
        current,
        id="traj-legacy-later",
        projection_version=TRAJECTORY_PROJECTION_VERSION_V1,
    )
    assert select_canonical_trajectories([current, legacy]) == [current]

    citations: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for _ in range(2):
        export_context._append_trajectory_citation(
            citations,
            seen,
            kind="finding",
            cited_id="finding-1",
            valid=True,
            source_event_type="claim_validation.completed",
            audit_sequence=1,
            dedupe_sequence=1,
        )
    assert len(citations) == 1

    assert (
        export_context._trajectory_precedent_match(
            replace(
                current,
                id="traj-prior",
                workflow_id="intent:prior",
                started_at_utc="2025-01-01T00:00:00Z",
                finished_at_utc="2025-01-01T00:01:00Z",
                subjects=(),
            ),
            trajectory=current,
            scope_set={"pkg/missing.py"},
        )
        is None
    )
