# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

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


def test_resolve_semantic_index_writer_returns_none_when_disabled() -> None:
    from codeclone.config.memory import SemanticConfig
    from codeclone.memory.semantic import resolve_semantic_index_writer

    assert resolve_semantic_index_writer(SemanticConfig(enabled=False)) is None


def test_hydrate_trajectory_skips_store_without_api_or_missing_record() -> None:
    from codeclone.memory.retrieval.semantic import _hydrate_trajectory

    hit = SemanticHit(source_id="traj-1", source="trajectory", score=0.4)

    class _StoreWithoutTrajectoryApi:
        pass

    assert _hydrate_trajectory(hit, _StoreWithoutTrajectoryApi(), 80) is None

    class _StoreMissingTrajectory:
        def find_trajectory(self, _trajectory_id: str) -> None:
            return None

    assert _hydrate_trajectory(hit, _StoreMissingTrajectory(), 80) is None


def test_hydrate_trajectory_hits_supports_compact_and_full_details(
    tmp_path: Path,
) -> None:
    from codeclone.memory.retrieval import service as retrieval_service

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        hit = SemanticHit(source_id=trajectory.id, source="trajectory", score=0.5)
        compact = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=[hit],
            detail_level="compact",
        )
        full = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=[hit],
            detail_level="full",
        )

    assert compact and full
    assert compact[0]["semantic_score"] == 0.5
    assert full[0]["semantic_score"] == 0.5
    assert "steps" in full[0]


def test_audit_event_row_and_primary_path_failure_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from codeclone.memory.retrieval import semantic

    db_path = tmp_path / "audit.sqlite3"
    db_path.touch()

    monkeypatch.setattr(
        semantic,
        "open_audit_db_readonly",
        lambda _path: (_ for _ in ()).throw(sqlite3.OperationalError("open failed")),
    )
    assert semantic.audit_event_row(db_path, "event") is None

    class _BrokenConnection:
        def execute(self, _sql: str, _params: object) -> object:
            raise sqlite3.OperationalError("query failed")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        semantic,
        "open_audit_db_readonly",
        lambda _path: _BrokenConnection(),
    )
    assert semantic.audit_event_row(db_path, "event") is None

    assert semantic._primary_path([]) is None
    trajectory = Trajectory(
        id="traj-empty",
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="run:one",
        intent_id=None,
        primary_run_id=None,
        first_run_id=None,
        last_run_id=None,
        report_digest=None,
        outcome="partial",
        quality_tier="partial",
        quality_score=0,
        labels=(),
        summary="summary",
        trajectory_digest="a" * 64,
        source_event_stream_digest="b" * 64,
        projection_version="trajectory-v2",
        event_count=0,
        step_count=0,
        incident_count=0,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:00Z",
        projected_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:00:00Z",
        steps=(),
        subjects=(),
        evidence=(),
    )
    assert semantic._primary_trajectory_path(trajectory) is None
