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
from codeclone.memory.jobs.worker import run_projection_job
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.trajectory.models import Trajectory
from codeclone.memory.trajectory.store import upsert_trajectory

from .memory_fixtures import memory_store
from .test_memory_experience_distiller import (
    _multi_agent_cohort,
    _single_agent_verification_cohort,
)


def _seed(
    store: SqliteEngineeringMemoryStore, project_id: str, cohort: list[Trajectory]
) -> None:
    for trajectory in cohort:
        upsert_trajectory(store.connection, replace(trajectory, project_id=project_id))
    store.connection.commit()


def test_distillation_persists_recurring_pattern(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed(store, project.id, _multi_agent_cohort(5))
        config = resolve_memory_config(root)

        payload = execute_experience_distillation(
            root_path=root, config=config, store=store, project=project
        )

        assert payload["status"] == "ok"
        assert payload["experiences_distilled"] == 1
        assert payload["trajectories_considered"] == 5

        experiences = store.list_experiences(project_id=project.id)
        assert len(experiences) == 1
        assert experiences[0].support == 5
        assert experiences[0].information_value >= 50
        assert experiences[0].project_id == project.id


def test_distillation_rejects_single_agent_quirk(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed(store, project.id, _single_agent_verification_cohort(6))
        config = resolve_memory_config(root)

        payload = execute_experience_distillation(
            root_path=root, config=config, store=store, project=project
        )

        # High support but one agent only -> tool quirk, not a system regularity.
        assert payload["status"] == "ok"
        assert payload["experiences_distilled"] == 0
        assert store.count_experiences(project_id=project.id) == 0


def test_distillation_replaces_wholesale(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed(store, project.id, _multi_agent_cohort(5))
        config = resolve_memory_config(root)

        first = execute_experience_distillation(
            root_path=root, config=config, store=store, project=project
        )
        second = execute_experience_distillation(
            root_path=root, config=config, store=store, project=project
        )

        # Derived state: a re-run replaces, never accumulates.
        assert first["experiences_distilled"] == 1
        assert second["experiences_distilled"] == 1
        assert store.count_experiences(project_id=project.id) == 1


def test_distillation_skipped_when_trajectories_disabled(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        _seed(store, project.id, _multi_agent_cohort(5))
        config = replace(resolve_memory_config(root), trajectories_enabled=False)

        payload = execute_experience_distillation(
            root_path=root, config=config, store=store, project=project
        )

        assert payload["status"] == "skipped"
        assert payload["reason"] == "trajectories_disabled"
        assert store.count_experiences(project_id=project.id) == 0


def test_projection_job_includes_experience_step(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        # Trajectories disabled -> every step skips without touching the audit
        # DB; the point is that the experience step is wired into the job.
        config = replace(resolve_memory_config(root), trajectories_enabled=False)

        _final_status, result, _error = run_projection_job(
            store,
            job_id="job-1",
            root_path=root,
            config=config,
            project=project,
            stimulus={"event_core_max_id": 0},
        )

        assert "experience" in result
        experience = result["experience"]
        assert isinstance(experience, dict)
        assert experience["action"] == "distill_experiences"
        assert experience["status"] == "skipped"
