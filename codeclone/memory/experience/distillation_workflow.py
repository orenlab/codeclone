# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Experience distillation runner.

Mirrors ``trajectory/rebuild_workflow.py``: a derived-state recompute that reads
the project's canonical trajectories, distills deterministic Experiences, and
replaces the project's experience set wholesale. Runs on the async projection
queue right after the trajectory rebuild (same lifecycle, no ritual)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from ...config.memory import MemoryConfig
from ...report.meta import current_report_timestamp_utc
from ..exceptions import MemoryContractError
from ..models import MemoryProject
from ..project import resolve_memory_db_path, resolve_project_identity
from ..sqlite_store import SqliteEngineeringMemoryStore
from .distiller import distill_experiences
from .models import EXPERIENCE_DISTILLATION_VERSION


class DistillExperiencesMeta(TypedDict):
    action: Literal["distill_experiences"]
    distillation_version: str


class DistillExperiencesOkPayload(DistillExperiencesMeta):
    status: Literal["ok"]
    experiences_distilled: int
    trajectories_considered: int


class DistillExperiencesSkippedPayload(DistillExperiencesMeta):
    status: Literal["skipped"]
    reason: str
    experiences_distilled: int


DistillExperiencesPayload = (
    DistillExperiencesOkPayload | DistillExperiencesSkippedPayload
)


def execute_experience_distillation(
    *,
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore | None = None,
    project: MemoryProject | None = None,
) -> DistillExperiencesPayload:
    base: DistillExperiencesMeta = {
        "action": "distill_experiences",
        "distillation_version": EXPERIENCE_DISTILLATION_VERSION,
    }
    if not config.trajectories_enabled:
        # Experiences are distilled from trajectories; no trajectories, nothing
        # to distill.
        return {
            **base,
            "status": "skipped",
            "reason": "trajectories_disabled",
            "experiences_distilled": 0,
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
        trajectories = active_store.list_canonical_trajectories_for_export(
            project_id=resolved_project.id
        )
        considered = len(trajectories)
        experiences = distill_experiences(
            trajectories, now=current_report_timestamp_utc()
        )
        distilled = active_store.replace_experiences(
            project_id=resolved_project.id, experiences=experiences
        )
    finally:
        if owns_store and active_store is not None:
            active_store.close()
    return {
        **base,
        "status": "ok",
        "experiences_distilled": distilled,
        "trajectories_considered": considered,
    }


__all__ = [
    "DistillExperiencesOkPayload",
    "DistillExperiencesPayload",
    "DistillExperiencesSkippedPayload",
    "execute_experience_distillation",
]
