# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.trajectory.agents import trajectory_agent_label
from codeclone.memory.trajectory.anomalies import detect_trajectory_anomalies

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow


def test_project_trajectory_records_agent_subject(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, _db_path):
        seed_trajectory_audit_workflow(
            root=root, audit_db=audit_db, intent_id="intent-agent-1"
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        items = store.list_trajectories(project_id=project.id, limit=5)
        trajectory = store.find_trajectory(items[0].id)
        assert trajectory is not None
        assert trajectory_agent_label(trajectory) == "test-agent"


def test_detect_trajectory_anomalies_flags_incomplete_cycle(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, _db_path):
        seed_trajectory_audit_workflow(
            root=root, audit_db=audit_db, intent_id="intent-partial-1"
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        items = store.list_trajectories(project_id=project.id, limit=1)
        trajectory = store.find_trajectory(items[0].id)
        assert trajectory is not None
        anomalies = detect_trajectory_anomalies(trajectory)
        kinds = {item.kind for item in anomalies}
        assert "missing_intent_clear" in kinds


def test_query_engineering_memory_trajectory_agents_mode(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, db_path):
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
            mode="trajectory_agents",
        )
        payload = result["payload"]
        assert isinstance(payload, dict)
        agents = payload.get("agents")
        assert isinstance(agents, list)
        assert payload.get("trajectory_count", 0) >= 1
        assert agents[0]["agent_label"] == "test-agent"


def test_query_engineering_memory_trajectory_dashboard_mode(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, db_path):
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
            mode="trajectory_dashboard",
            max_results=5,
        )
    payload = result["payload"]
    assert isinstance(payload, dict)
    assert "status" in payload
    assert "agents" in payload
    assert "anomalies" in payload
    assert "recent_trajectories" in payload
