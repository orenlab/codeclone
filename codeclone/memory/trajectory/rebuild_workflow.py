# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig
from ..exceptions import MemoryContractError
from ..models import MemoryProject
from ..project import resolve_memory_db_path, resolve_project_identity
from ..sqlite_store import SqliteEngineeringMemoryStore
from .models import TrajectoryProjectionResult


class RebuildTrajectoriesMeta(TypedDict):
    action: Literal["rebuild_trajectories"]
    projection_version: str


class RebuildTrajectoriesCounts(TypedDict):
    workflows_seen: int
    trajectories_created: int
    trajectories_updated: int
    trajectories_unchanged: int
    legacy_event_count: int


class RebuildTrajectoriesOkPayload(RebuildTrajectoriesMeta, RebuildTrajectoriesCounts):
    status: Literal["ok"]
    run_id: str


class RebuildTrajectoriesSkippedPayload(
    RebuildTrajectoriesMeta, RebuildTrajectoriesCounts
):
    status: Literal["skipped"]
    reason: str
    run_id: None


RebuildTrajectoriesPayload = (
    RebuildTrajectoriesOkPayload | RebuildTrajectoriesSkippedPayload
)


def execute_trajectory_rebuild(
    *,
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore | None = None,
    project: MemoryProject | None = None,
) -> RebuildTrajectoriesPayload:
    from .models import TRAJECTORY_PROJECTION_VERSION

    base: RebuildTrajectoriesMeta = {
        "action": "rebuild_trajectories",
        "projection_version": TRAJECTORY_PROJECTION_VERSION,
    }
    empty: RebuildTrajectoriesCounts = {
        "workflows_seen": 0,
        "trajectories_created": 0,
        "trajectories_updated": 0,
        "trajectories_unchanged": 0,
        "legacy_event_count": 0,
    }
    if not config.trajectories_enabled:
        return {
            **base,
            **empty,
            "status": "skipped",
            "reason": "trajectories_disabled",
            "run_id": None,
        }
    owns_store = store is None
    active_store = store
    try:
        resolved_project = project or resolve_project_identity(root_path)
        if active_store is None:
            db_path = resolve_memory_db_path(root_path, config)
            if not db_path.exists():
                raise MemoryContractError(
                    f"Engineering memory database not found: {db_path}. "
                    "Run memory init or "
                    "manage_engineering_memory(action='refresh_from_run')."
                )
            active_store = SqliteEngineeringMemoryStore(db_path)
        audit_db_path = resolve_audit_path(
            root_path=root_path,
            value=DEFAULT_AUDIT_PATH,
        )
        result: TrajectoryProjectionResult = (
            active_store.rebuild_trajectories_from_audit(
                project=resolved_project,
                root_path=root_path,
                audit_db_path=audit_db_path,
            )
        )
    finally:
        if owns_store and active_store is not None:
            active_store.close()
    return {
        **base,
        "status": "ok",
        "run_id": result.run.id,
        "workflows_seen": result.run.workflows_seen,
        "trajectories_created": result.run.trajectories_created,
        "trajectories_updated": result.run.trajectories_updated,
        "trajectories_unchanged": result.run.trajectories_unchanged,
        "legacy_event_count": result.run.legacy_event_count,
    }


__all__ = [
    "RebuildTrajectoriesOkPayload",
    "RebuildTrajectoriesPayload",
    "RebuildTrajectoriesSkippedPayload",
    "execute_trajectory_rebuild",
]
