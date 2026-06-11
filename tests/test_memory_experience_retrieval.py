# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.experience.distillation_workflow import (
    execute_experience_distillation,
)
from codeclone.memory.models import MemoryProject
from codeclone.memory.retrieval.service import get_relevant_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.trajectory.store import upsert_trajectory

from .memory_fixtures import memory_store
from .test_memory_experience_distiller import _FAMILY, _multi_agent_cohort


def _seed_and_distill(
    root: Path, project: MemoryProject, store: SqliteEngineeringMemoryStore
) -> None:
    for trajectory in _multi_agent_cohort(5):
        upsert_trajectory(store.connection, replace(trajectory, project_id=project.id))
    store.connection.commit()
    execute_experience_distillation(
        root_path=root,
        config=resolve_memory_config(root),
        store=store,
        project=project,
    )


def test_relevant_memory_surfaces_experiences(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed_and_distill(root, project, store)

        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(f"{_FAMILY}/store.py",),
            scope_resolved_from="explicit",
            detail_level="full",
        )

        experiences = result["experiences"]
        assert isinstance(experiences, list)
        assert result["experience_count"] == 1
        experience = experiences[0]
        assert experience["subject_family"] == _FAMILY
        assert experience["support"] == 5
        # Multi-agent facet and trajectory evidence both surface.
        assert {facet["agent_family"] for facet in experience["agent_facets"]} == {
            "claude-code",
            "cursor-vscode",
        }
        assert len(experience["evidence_trajectory_ids"]) >= 1
        # Advisory contract, exactly like trajectories.
        policy = result["retrieval_policy"]
        assert isinstance(policy, dict)
        assert policy["experiences_do_not_authorize_edits"] is True


def test_relevant_memory_compacts_experience_statement_and_evidence(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed_and_distill(root, project, store)
        experience = store.list_experiences(project_id=project.id)[0]
        store.replace_experiences(
            project_id=project.id,
            experiences=[replace(experience, statement="x" * 300)],
        )

        compact = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(f"{_FAMILY}/store.py",),
            scope_resolved_from="explicit",
            detail_level="compact",
        )
        full = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(f"{_FAMILY}/store.py",),
            scope_resolved_from="explicit",
            detail_level="full",
        )

    by_detail: dict[str, dict[str, object]] = {}
    for detail, payload in (("compact", compact), ("full", full)):
        experiences = payload["experiences"]
        assert isinstance(experiences, list)
        experience_payload = experiences[0]
        assert isinstance(experience_payload, dict)
        by_detail[detail] = experience_payload
    compact_experience = by_detail["compact"]
    full_experience = by_detail["full"]
    assert compact_experience["statement_length"] == 300
    assert compact_experience["statement_truncated"] is True
    compact_statement = compact_experience["statement"]
    assert isinstance(compact_statement, str)
    assert len(compact_statement) < 300
    assert compact_experience["evidence_count"] == 5
    assert "evidence_trajectory_ids" not in compact_experience
    assert full_experience["statement"] == "x" * 300
    full_evidence = full_experience["evidence_trajectory_ids"]
    assert isinstance(full_evidence, list)
    assert len(full_evidence) == 5
    assert "evidence_count" not in full_experience


def test_experiences_are_typed_separate_from_records(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed_and_distill(root, project, store)

        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(f"{_FAMILY}/store.py",),
            scope_resolved_from="explicit",
        )

        # No memory records were written; the pattern lives only in experiences[].
        assert result["records"] == []
        assert result["experiences"]


def test_experiences_scoped_by_family(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed_and_distill(root, project, store)

        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("some/unrelated/place.py",),
            scope_resolved_from="explicit",
        )

        assert result["experiences"] == []
        assert result["experience_count"] == 0
