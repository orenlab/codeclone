# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.memory.models import MemoryRecord, MemorySubject
from codeclone.memory.retrieval.semantic import semantic_search
from codeclone.memory.semantic.models import SemanticHit, SemanticIndexStatus
from codeclone.memory.trajectory.models import Trajectory, TrajectorySubject

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow

_PROVIDER = DeterministicHashEmbeddingProvider(dimension=8)


class _FakeIndex:
    def __init__(self, hits: list[SemanticHit]) -> None:
        self._hits = hits

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        hits = (
            self._hits
            if source is None
            else [hit for hit in self._hits if hit.source == source]
        )
        return hits[:k]

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=True, indexed_count=len(self._hits))


class _StoreWithoutTrajectory:
    def find_record(self, record_id: str) -> MemoryRecord | None:
        return None

    def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]:
        return []


def test_semantic_search_hydrates_trajectory_hit(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        trajectory = replace(
            trajectory,
            subjects=(
                TrajectorySubject(
                    subject_kind="path",
                    subject_key="pkg/service.py",
                    relation="about",
                ),
            ),
        )
        index = _FakeIndex(
            [SemanticHit(source_id=trajectory.id, source="trajectory", score=0.75)]
        )

        class _TrajectoryStore:
            def find_record(self, record_id: str) -> MemoryRecord | None:
                return None

            def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]:
                return []

            def find_trajectory(self, trajectory_id: str) -> Trajectory | None:
                return trajectory if trajectory_id == trajectory.id else None

        results = semantic_search(
            index=index,
            provider=_PROVIDER,
            store=_TrajectoryStore(),
            audit_db_path=Path("missing.sqlite3"),
            query="service workflow",
            limit=5,
            preview_chars=80,
        )
    assert len(results) == 1
    assert results[0].source == "trajectory"
    assert results[0].subject_path == "pkg/service.py"
    assert results[0].preview


def test_semantic_search_skips_trajectory_without_store_method() -> None:
    index = _FakeIndex(
        [SemanticHit(source_id="traj-1", source="trajectory", score=0.5)]
    )
    results = semantic_search(
        index=index,
        provider=_PROVIDER,
        store=_StoreWithoutTrajectory(),
        audit_db_path=Path("missing.sqlite3"),
        query="workflow",
        limit=5,
        preview_chars=40,
    )
    assert results == []


def test_semantic_search_skips_unknown_trajectory_source_without_store() -> None:
    index = _FakeIndex(
        [SemanticHit(source_id="traj-1", source="trajectory", score=0.5)]
    )
    results = semantic_search(
        index=index,
        provider=_PROVIDER,
        store=None,
        audit_db_path=Path("missing.sqlite3"),
        query="workflow",
        limit=5,
        preview_chars=40,
    )
    assert results == []
