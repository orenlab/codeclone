# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Stores whose ids collide, for pinning the short-id contract of a surface.

A short id is ambiguous only when two objects share its prefix, and ids are
minted from random hex, so no production call can be asked for a collision.
These fixtures build one: they take the record production writes and rewrite
only its id, which keeps every other field exactly what the real draft path
produced while making the ambiguity branch reachable at all.

The seeding lives here rather than in the test module because a test whose
subject is a CLI surface reaches its store through fixtures, not through the
store packages directly -- the boundary the architecture ratchet holds.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from codeclone.memory.governance import approve_record, record_candidate
from codeclone.memory.models import MemoryProject
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.store import MEMORY_ID_CANDIDATE_LIMIT
from codeclone.memory.trajectory.models import (
    TRAJECTORY_PROJECTION_VERSION,
    Trajectory,
)
from codeclone.memory.trajectory.store import upsert_trajectory
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_project_db_paths

__all__ = [
    "MEMORY_ID_CANDIDATE_LIMIT",
    "collide_id",
    "memory_repo",
    "open_memory_store",
    "promote_to_active",
    "read_record_status",
    "record_resolver_calls",
    "resolve_id_through_mcp",
    "seed_colliding_draft",
    "seed_colliding_trajectory",
]


def collide_id(family: str, shared_prefix: str, suffix: str) -> str:
    """A full id opening with ``shared_prefix``, made unique by ``suffix``."""

    return f"{family}-{f'{shared_prefix}{suffix}'.ljust(32, '0')}"


@contextmanager
def memory_repo(tmp_path: Path) -> Iterator[tuple[Path, MemoryProject]]:
    """An initialized memory store at the repository root a CLI run resolves."""

    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    project, db_path = memory_project_db_paths(root)
    store = SqliteEngineeringMemoryStore(db_path)
    store.initialize(project)
    try:
        yield root, project
    finally:
        store.close()


@contextmanager
def open_memory_store(root: Path) -> Iterator[SqliteEngineeringMemoryStore]:
    _project, db_path = memory_project_db_paths(root)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        yield store
    finally:
        store.close()


def seed_colliding_draft(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    record_id: str,
    statement: str,
) -> None:
    """One draft written through the production draft shape, then re-idded."""

    drafted = record_candidate(
        store,
        project=project,
        record_type="risk_note",
        statement=statement,
        subject_path=f"pkg/{record_id[-6:]}.py",
        max_candidates=100,
    )
    store.write_record(
        dataclasses.replace(
            drafted,
            id=record_id,
            identity_key=f"{drafted.identity_key}:{record_id}",
        )
    )


def promote_to_active(store: SqliteEngineeringMemoryStore, record_id: str) -> None:
    approve_record(store, record_id=record_id, approved_by="tester")


def read_record_status(root: Path, record_id: str) -> str | None:
    with open_memory_store(root) as store:
        record = store.find_record(record_id)
    return None if record is None else record.status


def seed_colliding_trajectory(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    trajectory_id: str,
) -> None:
    now = current_report_timestamp_utc()
    upsert_trajectory(
        store.connection,
        Trajectory(
            id=trajectory_id,
            project_id=project_id,
            repo_root_digest="digest",
            workflow_id=f"intent:{trajectory_id}",
            intent_id=trajectory_id,
            primary_run_id="run-1",
            first_run_id="run-1",
            last_run_id="run-1",
            report_digest=None,
            outcome="accepted",
            quality_tier="verified",
            quality_score=90,
            labels=(),
            summary=f"trajectory {trajectory_id}",
            trajectory_digest=f"digest-{trajectory_id}",
            source_event_stream_digest="stream",
            projection_version=TRAJECTORY_PROJECTION_VERSION,
            event_count=1,
            step_count=0,
            incident_count=0,
            started_at_utc=now,
            finished_at_utc=now,
            projected_at_utc=now,
            updated_at_utc=now,
            steps=(),
            subjects=(),
            evidence=(),
        ),
    )
    store.connection.commit()


def resolve_id_through_mcp(
    root: Path, *, mode: str, record_id: str
) -> dict[str, object]:
    """What the MCP query surface answers for this id, on this same store."""

    project, db_path = memory_project_db_paths(root)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        return query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode=mode,
            record_id=record_id,
        )
    finally:
        store.close()


@contextmanager
def record_resolver_calls() -> Iterator[list[str]]:
    """Every prefix the record lane's own resolver is asked to resolve.

    This records the edge rather than the wording: a surface that grew a
    private resolver would print the same lines and never appear here, so a
    test that asserts on output alone cannot tell the two apart.
    """

    seen: list[str] = []
    owner: Callable[..., object] = SqliteEngineeringMemoryStore.resolve_record_id_prefix

    def spy(self: SqliteEngineeringMemoryStore, **kwargs: object) -> object:
        seen.append(str(kwargs.get("prefix")))
        return owner(self, **kwargs)

    SqliteEngineeringMemoryStore.resolve_record_id_prefix = spy  # type: ignore[method-assign,assignment]
    try:
        yield seen
    finally:
        SqliteEngineeringMemoryStore.resolve_record_id_prefix = owner  # type: ignore[method-assign,assignment]
