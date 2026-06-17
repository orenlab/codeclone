# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.semantic.models import SemanticHit
from codeclone.memory.trajectory.retrieval import (
    COMPACT_TRAJECTORY_SUBJECT_LIMIT,
)

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow


def _assert_compact_trajectory(payload: object) -> None:
    assert isinstance(payload, dict)
    assert "quality_contract" not in payload
    assert "steps" not in payload
    assert "evidence" not in payload
    subjects = payload.get("subjects")
    assert isinstance(subjects, list)
    assert len(subjects) <= COMPACT_TRAJECTORY_SUBJECT_LIMIT
    assert isinstance(payload.get("subject_count"), int)
    assert isinstance(payload.get("subjects_truncated"), bool)


@pytest.mark.parametrize(
    "mode",
    ("trajectory_search", "trajectory_anomalies", "trajectory_dashboard"),
)
def test_compact_trajectory_modes_honor_declared_detail_level(
    tmp_path: Path,
    mode: str,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode=mode,
            query="recover service" if mode == "trajectory_search" else None,
            detail_level="compact",
        )

    assert result["detail_level"] == "compact"
    payload = result["payload"]
    assert isinstance(payload, dict)
    if mode == "trajectory_dashboard":
        anomalies = payload["anomalies"]
        assert isinstance(anomalies, dict)
        trajectories = anomalies["trajectories"]
    else:
        trajectories = payload["trajectories"]
    assert isinstance(trajectories, list)
    assert trajectories
    _assert_compact_trajectory(trajectories[0])


def test_trajectory_search_full_keeps_quality_contract(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_search",
            query="recover service",
            detail_level="full",
        )

    assert result["detail_level"] == "full"
    payload = result["payload"]
    assert isinstance(payload, dict)
    trajectories = payload["trajectories"]
    assert isinstance(trajectories, list)
    assert trajectories
    assert "quality_contract" in trajectories[0]


def test_semantic_trajectory_hydration_respects_detail_level(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        hits = [
            SemanticHit(
                source_id=trajectory.id,
                source="trajectory",
                score=0.75,
            )
        ]
        compact = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=hits,
            detail_level="compact",
        )
        full = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=hits,
            detail_level="full",
        )

    _assert_compact_trajectory(compact[0])
    assert compact[0]["semantic_score"] == 0.75
    assert "quality_contract" in full[0]
    assert "steps" in full[0]
