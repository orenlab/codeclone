# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.experience.distillation_workflow import (
    execute_experience_distillation,
)
from codeclone.memory.governance import promote_experience
from codeclone.memory.models import MemoryProject
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.trajectory.store import upsert_trajectory

from .memory_fixtures import memory_store
from .test_memory_experience_distiller import _multi_agent_cohort


def _distilled_experience_id(
    root: Path, project: MemoryProject, store: SqliteEngineeringMemoryStore
) -> str:
    for trajectory in _multi_agent_cohort(5):
        upsert_trajectory(store.connection, replace(trajectory, project_id=project.id))
    store.connection.commit()
    execute_experience_distillation(
        root_path=root,
        config=resolve_memory_config(root),
        store=store,
        project=project,
    )
    experiences = store.list_experiences(project_id=project.id)
    assert len(experiences) == 1
    return experiences[0].id


def test_promote_experience_creates_draft_with_trajectory_evidence(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        experience_id = _distilled_experience_id(root, project, store)
        config = resolve_memory_config(root)

        record = promote_experience(
            store,
            project=project,
            experience_id=experience_id,
            max_candidates=config.max_candidates,
        )

        # A human-approvable draft, not an active assertion.
        assert record.status == "draft"
        assert record.type == "risk_note"
        assert record.confidence == "inferred"
        assert record.payload is not None
        assert record.payload.get("promoted_from_experience") == experience_id
        # One trajectory evidence row per proof trajectory.
        assert store.count_evidence_for_memory(record.id) == 5


def test_promote_experience_is_idempotent(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        experience_id = _distilled_experience_id(root, project, store)
        config = resolve_memory_config(root)

        promote_experience(
            store,
            project=project,
            experience_id=experience_id,
            max_candidates=config.max_candidates,
        )
        with pytest.raises(MemoryContractError, match="already promoted"):
            promote_experience(
                store,
                project=project,
                experience_id=experience_id,
                max_candidates=config.max_candidates,
            )


def test_promote_unknown_experience_raises(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        config = resolve_memory_config(root)

        with pytest.raises(MemoryContractError, match="not found"):
            promote_experience(
                store,
                project=project,
                experience_id="exp-doesnotexist",
                max_candidates=config.max_candidates,
            )
