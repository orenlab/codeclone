# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic workspace drift projection for in-memory MCP runs."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...cache.entries import FileStat
from ...cache.store import file_stat_signature
from ...contracts.errors import ValidationError
from ...scanner import iter_py_files
from ._session_shared import MCPRunRecord
from ._workspace_hygiene import DirtySnapshot, collect_dirty_snapshot

WorkspaceDriftStatus = Literal["fresh", "drifted", "unknown"]
WorkspaceDriftStrength = Literal["mtime_size", "mtime_size_plus_git"]


@dataclass(frozen=True, slots=True)
class WorkspaceDrift:
    status: WorkspaceDriftStatus
    drifted_files: tuple[str, ...]
    added_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    topology_drift: bool
    strength: WorkspaceDriftStrength


def build_run_manifest(
    *,
    root: Path,
    filepaths: Iterable[str],
) -> dict[str, FileStat]:
    """Capture repo-relative source signatures for one completed discovery."""
    manifest: dict[str, FileStat] = {}
    for filepath in sorted(set(filepaths)):
        relative_path = _repo_relative_path(root, filepath)
        if relative_path is None:
            continue
        try:
            manifest[relative_path] = file_stat_signature(filepath)
        except OSError:
            continue
    return dict(sorted(manifest.items()))


def compute_drift(
    record: MCPRunRecord,
    paths: Sequence[str] | None = None,
) -> WorkspaceDrift:
    """Compare a run's source snapshot with current stat, topology, and git state."""
    manifest = record.manifest
    if manifest is None:
        return WorkspaceDrift(
            status="unknown",
            drifted_files=(),
            added_files=(),
            deleted_files=(),
            topology_drift=False,
            strength=_drift_strength(record.dirty_snapshot, None),
        )

    selected_paths = _selected_paths(paths)
    manifest_paths = frozenset(manifest)
    current_paths = _current_source_paths(record.root)
    topology_known = current_paths is not None
    current_source_paths = current_paths or frozenset()

    deleted_files = (
        tuple(
            sorted(
                path
                for path in manifest_paths - current_source_paths
                if _path_selected(path, selected_paths)
            )
        )
        if topology_known
        else ()
    )
    added_files = (
        tuple(
            sorted(
                path
                for path in current_source_paths - manifest_paths
                if _path_selected(path, selected_paths)
            )
        )
        if topology_known
        else ()
    )

    drifted: set[str] = set()
    for path in sorted(manifest_paths):
        if not _path_selected(path, selected_paths):
            continue
        try:
            live_stat = file_stat_signature(str(record.root / path))
        except OSError:
            if not topology_known:
                drifted.add(path)
            continue
        if live_stat != manifest[path]:
            drifted.add(path)

    current_dirty_snapshot = collect_dirty_snapshot(record.root)
    git_drifted = _dirty_snapshot_delta(
        before=record.dirty_snapshot,
        after=current_dirty_snapshot,
    )
    source_universe = manifest_paths | current_source_paths
    drifted.update(
        path
        for path in git_drifted
        if path in source_universe and _path_selected(path, selected_paths)
    )
    drifted.difference_update(deleted_files)
    drifted.difference_update(added_files)

    has_drift = bool(drifted or added_files or deleted_files)
    status: WorkspaceDriftStatus
    if has_drift:
        status = "drifted"
    elif topology_known:
        status = "fresh"
    else:
        status = "unknown"
    return WorkspaceDrift(
        status=status,
        drifted_files=tuple(sorted(drifted)),
        added_files=added_files,
        deleted_files=deleted_files,
        topology_drift=bool(added_files or deleted_files),
        strength=_drift_strength(record.dirty_snapshot, current_dirty_snapshot),
    )


def _current_source_paths(root: Path) -> frozenset[str] | None:
    try:
        return frozenset(
            relative_path
            for filepath in iter_py_files(str(root))
            if (relative_path := _repo_relative_path(root, filepath)) is not None
        )
    except (OSError, RuntimeError, ValidationError):
        return None


def _repo_relative_path(root: Path, filepath: str) -> str | None:
    root_path = root.resolve()
    candidate = Path(filepath)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    try:
        relative = candidate.relative_to(root_path)
    except ValueError:
        return None
    normalized = relative.as_posix().strip("/")
    return normalized or None


def _selected_paths(paths: Sequence[str] | None) -> frozenset[str] | None:
    if paths is None:
        return None
    return frozenset(
        normalized
        for path in paths
        if (normalized := path.strip().replace("\\", "/").strip("/"))
    )


def _path_selected(path: str, selected_paths: frozenset[str] | None) -> bool:
    if selected_paths is None:
        return True
    return any(
        path == selected or path.startswith(f"{selected}/")
        for selected in selected_paths
    )


def _dirty_snapshot_delta(
    *,
    before: DirtySnapshot | None,
    after: DirtySnapshot,
) -> frozenset[str]:
    if before is None or not before.git_available or not after.git_available:
        return frozenset()
    before_entries = before.entry_map()
    after_entries = after.entry_map()
    return frozenset(
        path
        for path in before_entries.keys() | after_entries.keys()
        if before_entries.get(path) != after_entries.get(path)
    )


def _drift_strength(
    before: DirtySnapshot | None,
    after: DirtySnapshot | None,
) -> WorkspaceDriftStrength:
    if (
        before is not None
        and after is not None
        and before.git_available
        and after.git_available
    ):
        return "mtime_size_plus_git"
    return "mtime_size"


__all__ = [
    "WorkspaceDrift",
    "WorkspaceDriftStatus",
    "WorkspaceDriftStrength",
    "build_run_manifest",
    "compute_drift",
]
