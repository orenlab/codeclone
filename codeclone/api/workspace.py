# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal R3 workspace-status door over the canonical R2 Git owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..paths.git_snapshot import collect_git_workspace_snapshot


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkspaceDirtyPathsDTO:
    git_available: bool
    dirty_paths: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkspaceDirtyEntryDTO:
    path: str
    status_xy: str
    digest: str | None
    digest_status: str


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkspaceDirtySnapshotDTO:
    git_available: bool
    captured_at_utc: str
    entries: tuple[WorkspaceDirtyEntryDTO, ...]


def _captured_at_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def collect_workspace_dirty_paths(*, root: Path) -> WorkspaceDirtyPathsDTO:
    snapshot = collect_git_workspace_snapshot(root, include_digests=False)
    return WorkspaceDirtyPathsDTO(
        git_available=snapshot.git_available,
        dirty_paths=tuple(entry.path for entry in snapshot.entries),
    )


def collect_workspace_dirty_snapshot(*, root: Path) -> WorkspaceDirtySnapshotDTO:
    snapshot = collect_git_workspace_snapshot(root, include_digests=True)
    return WorkspaceDirtySnapshotDTO(
        git_available=snapshot.git_available,
        captured_at_utc=_captured_at_utc(),
        entries=tuple(
            WorkspaceDirtyEntryDTO(
                path=entry.path,
                status_xy=entry.status_xy,
                digest=entry.digest,
                digest_status=entry.digest_status,
            )
            for entry in snapshot.entries
        ),
    )


__all__ = [
    "WorkspaceDirtyEntryDTO",
    "WorkspaceDirtyPathsDTO",
    "WorkspaceDirtySnapshotDTO",
    "collect_workspace_dirty_paths",
    "collect_workspace_dirty_snapshot",
]
