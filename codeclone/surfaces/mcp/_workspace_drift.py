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

from ...cache.store import file_stat_signature
from ...contracts.errors import ValidationError
from ...models import FileStat
from ...scanner import iter_py_files
from ._session_shared import MCPRunRecord
from ._workspace_hygiene import DirtySnapshot, collect_dirty_snapshot

WorkspaceDriftStatus = Literal["fresh", "drifted", "unknown"]
WorkspaceDriftStrength = Literal["mtime_size", "mtime_size_plus_git"]


@dataclass(frozen=True, slots=True)
class WorkspaceDrift:
    """One drift verdict plus the evidence class that verdict actually rests on.

    ``strength`` names the evidence held, never the mechanism consulted. Git
    being reachable is not a witness for a path git never spoke about, so the
    stronger label is earned per path and reported over the whole comparison.
    """

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
            strength=_drift_strength(
                compared_paths=frozenset(),
                witnessed_paths=_git_witnessed_paths(record.dirty_snapshot, None),
            ),
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

    # The paths this run actually compares byte-for-byte. `strength` is a
    # statement about exactly this set, so it is named once and reused.
    compared_paths = frozenset(
        path for path in manifest_paths if _path_selected(path, selected_paths)
    )
    drifted: set[str] = set()
    for path in sorted(compared_paths):
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
        strength=_drift_strength(
            compared_paths=compared_paths,
            witnessed_paths=_git_witnessed_paths(
                record.dirty_snapshot,
                current_dirty_snapshot,
            ),
        ),
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


def _git_witnessed_paths(
    before: DirtySnapshot | None,
    after: DirtySnapshot | None,
) -> frozenset[str]:
    """Paths git reported individually, under a digest that moves on content.

    A path is witnessed only when an entry is keyed on that exact path and
    carries a content digest, because that digest is the whole reason the
    before/after delta can see an edit the stat lanes miss. Measured
    2026-08-31 against a real repository, two shapes fail that test while git
    is perfectly reachable: ``git status --porcelain=v1`` collapses an
    untracked directory into a single digest-less entry keyed on the
    directory, and it never lists an ignored file at all -- yet both are
    scanned into the run manifest and compared.

    Absence from a snapshot is deliberately not read as evidence. A clean
    tracked file and an ignored file are the same absence here, and telling
    them apart means asking git a question this run never asked. The honest
    move is to narrow the claim to the witness in hand, not to widen the
    mechanism until the old claim comes true.
    """
    if before is None or after is None:
        return frozenset()
    if not before.git_available or not after.git_available:
        return frozenset()
    return frozenset(
        path
        for snapshot in (before, after)
        for path, entry in snapshot.entry_map().items()
        if entry.digest is not None
    )


def _drift_strength(
    *,
    compared_paths: frozenset[str],
    witnessed_paths: frozenset[str],
) -> WorkspaceDriftStrength:
    """Report the weakest evidence any compared path carries.

    One label stands over a per-path property, so it may only claim the git
    witness when every content-compared path holds it: a single blind path is
    enough to hide a same-stat edit behind a ``fresh`` verdict. An empty
    comparison is vacuously contained in any witness set and holds none of
    it, so it claims none -- otherwise the run that checked the least would
    report the strongest evidence.
    """
    if compared_paths and compared_paths <= witnessed_paths:
        return "mtime_size_plus_git"
    return "mtime_size"


__all__ = [
    "WorkspaceDrift",
    "WorkspaceDriftStatus",
    "WorkspaceDriftStrength",
    "build_run_manifest",
    "compute_drift",
]
