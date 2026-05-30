# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Git working-tree hygiene evaluation for workspace change control."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ._workspace_intent_lifecycle import (
    WorkspaceIntentStatus,
    is_terminal_workspace_intent_status,
)
from ._workspace_intent_store import WorkspaceIntentStore
from ._workspace_intents import (
    IntentOwnership,
    _scope_all_sets,
    classify_intent_ownership,
    utc_now,
)

_FOREIGN_DIRTY_OWNERSHIP: frozenset[IntentOwnership] = frozenset(
    {
        IntentOwnership.FOREIGN_ACTIVE,
        IntentOwnership.FOREIGN_STALE,
    }
)

_DIRTY_SUMMARY_SAMPLE_LIMIT = 10
_BASE_DIRTY_SCOPE_MESSAGE = "Uncommitted changes overlap your declared scope."

DIRTY_SCOPE_POLICY_BLOCK: Final = "block"
DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP: Final = "continue_own_wip"
VALID_DIRTY_SCOPE_POLICIES: frozenset[str] = frozenset(
    {
        DIRTY_SCOPE_POLICY_BLOCK,
        DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP,
    }
)


@dataclass(frozen=True, slots=True)
class DirtyPathsResult:
    git_available: bool
    dirty_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForeignDirtyOverlap:
    path: str
    foreign_intent_id: str
    foreign_persisted_status: str
    foreign_ownership: str
    foreign_agent_label: str
    message: str

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "foreign_intent_id": self.foreign_intent_id,
            "foreign_persisted_status": self.foreign_persisted_status,
            "foreign_ownership": self.foreign_ownership,
            "foreign_agent_label": self.foreign_agent_label,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceHygieneResult:
    git_available: bool
    dirty_paths: tuple[str, ...]
    dirty_paths_in_scope: tuple[str, ...]
    dirty_paths_outside_scope: tuple[str, ...]
    foreign_dirty_overlaps: tuple[ForeignDirtyOverlap, ...]
    blocks_edit: bool
    unacknowledged_dirty_in_scope: tuple[str, ...] = ()
    blocks_finish: bool = False

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "git_available": self.git_available,
            "dirty_paths_in_scope": list(self.dirty_paths_in_scope),
            "dirty_paths_outside_scope": list(self.dirty_paths_outside_scope),
            "foreign_dirty_overlaps": [
                item.to_payload() for item in self.foreign_dirty_overlaps
            ],
            "blocks_edit": self.blocks_edit,
        }
        if self.unacknowledged_dirty_in_scope:
            payload["unacknowledged_dirty_in_scope"] = list(
                self.unacknowledged_dirty_in_scope
            )
        if self.blocks_finish:
            payload["blocks_finish"] = True
        return payload


def collect_dirty_paths(
    root: Path,
    *,
    scoped_paths: Sequence[str] | None = None,
) -> DirtyPathsResult:
    """Collect repo-relative dirty paths from the git working tree."""
    if not _git_available(root):
        return DirtyPathsResult(git_available=False, dirty_paths=())
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return DirtyPathsResult(git_available=False, dirty_paths=())
    dirty = _dirty_paths_from_porcelain(completed.stdout)
    if scoped_paths is not None:
        scope_set = {_normalize_path(path) for path in scoped_paths if path.strip()}
        dirty = tuple(sorted(path for path in dirty if _path_in_scope(path, scope_set)))
    return DirtyPathsResult(git_available=True, dirty_paths=dirty)


def workspace_dirty_summary(*, root: Path) -> dict[str, object]:
    """Repo-level dirty summary for list_workspace (no scoped blocking)."""
    dirty_result = collect_dirty_paths(root)
    if not dirty_result.git_available:
        return {
            "git_available": False,
            "dirty_paths_count": 0,
            "dirty_paths_sample": [],
            "sample_truncated": False,
        }
    sample, truncated = _bounded_sample(dirty_result.dirty_paths)
    return {
        "git_available": True,
        "dirty_paths_count": len(dirty_result.dirty_paths),
        "dirty_paths_sample": list(sample),
        "sample_truncated": truncated,
    }


def evaluate_scoped_hygiene(
    *,
    root: Path,
    allowed_files: Sequence[str],
    allowed_related: Sequence[str] | None = None,
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None = None,
) -> WorkspaceHygieneResult:
    """Evaluate scoped hygiene for start/finish workflow responses."""
    blocking_scope = {_normalize_path(path) for path in allowed_files if path.strip()}
    related_scope = {
        _normalize_path(path) for path in (allowed_related or ()) if path.strip()
    } - blocking_scope
    evaluation_scope = blocking_scope | related_scope
    dirty_result = collect_dirty_paths(
        root,
        scoped_paths=tuple(sorted(evaluation_scope)) if evaluation_scope else None,
    )
    if not dirty_result.git_available:
        return WorkspaceHygieneResult(
            git_available=False,
            dirty_paths=(),
            dirty_paths_in_scope=(),
            dirty_paths_outside_scope=(),
            foreign_dirty_overlaps=(),
            blocks_edit=False,
        )
    dirty_in_blocking = tuple(
        sorted(
            path
            for path in dirty_result.dirty_paths
            if _path_in_scope(path, blocking_scope)
        )
    )
    dirty_outside = tuple(
        sorted(
            path
            for path in dirty_result.dirty_paths
            if not _path_in_scope(path, blocking_scope)
        )
    )
    foreign_overlaps = _foreign_dirty_overlaps(
        dirty_paths=dirty_in_blocking,
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    )
    blocks_edit = bool(dirty_in_blocking)
    return WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=dirty_result.dirty_paths,
        dirty_paths_in_scope=dirty_in_blocking,
        dirty_paths_outside_scope=dirty_outside,
        foreign_dirty_overlaps=foreign_overlaps,
        blocks_edit=blocks_edit,
    )


def finish_hygiene_check(
    *,
    root: Path,
    allowed_files: Sequence[str],
    allowed_related: Sequence[str] | None,
    resolved_files: Sequence[str],
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str,
) -> WorkspaceHygieneResult:
    """Finish-time hygiene gate against declared scope and evidence."""
    hygiene = evaluate_scoped_hygiene(
        root=root,
        allowed_files=allowed_files,
        allowed_related=allowed_related,
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    )
    if not hygiene.git_available:
        return hygiene
    evidence = {_normalize_path(path) for path in resolved_files if path.strip()}
    blocking_scope = {_normalize_path(path) for path in allowed_files if path.strip()}
    dirty_blocking = {
        path
        for path in hygiene.dirty_paths_in_scope
        if _path_in_scope(path, blocking_scope)
    }
    unacknowledged = tuple(sorted(dirty_blocking - evidence))
    blocks_finish = bool(unacknowledged) or bool(hygiene.foreign_dirty_overlaps)
    return WorkspaceHygieneResult(
        git_available=hygiene.git_available,
        dirty_paths=hygiene.dirty_paths,
        dirty_paths_in_scope=hygiene.dirty_paths_in_scope,
        dirty_paths_outside_scope=hygiene.dirty_paths_outside_scope,
        foreign_dirty_overlaps=hygiene.foreign_dirty_overlaps,
        blocks_edit=hygiene.blocks_edit,
        unacknowledged_dirty_in_scope=unacknowledged,
        blocks_finish=blocks_finish,
    )


def _foreign_dirty_overlaps(
    *,
    dirty_paths: Sequence[str],
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> tuple[ForeignDirtyOverlap, ...]:
    if not dirty_paths:
        return ()
    now = utc_now()
    overlaps: list[ForeignDirtyOverlap] = []
    for record in store.list_records_for_hygiene():
        if (
            record.agent_pid == own_pid and record.agent_start_epoch == own_start_epoch
        ) or (own_intent_id is not None and record.intent_id == own_intent_id):
            continue
        if is_terminal_workspace_intent_status(record.status):
            continue
        if record.status == WorkspaceIntentStatus.QUEUED.value:
            continue
        foreign_allowed, _, _ = _scope_all_sets(record.scope)
        scoped_dirty_paths = [
            path for path in dirty_paths if _path_in_scope(path, foreign_allowed)
        ]
        ownership = classify_intent_ownership(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            now=now,
        )
        if ownership not in _FOREIGN_DIRTY_OWNERSHIP:
            continue
        overlaps.extend(
            ForeignDirtyOverlap(
                path=path,
                foreign_intent_id=record.intent_id,
                foreign_persisted_status=record.status,
                foreign_ownership=ownership.value,
                foreign_agent_label=record.agent_label,
                message=(
                    f"{_BASE_DIRTY_SCOPE_MESSAGE} Foreign intent "
                    f"{record.intent_id} previously declared this path."
                ),
            )
            for path in scoped_dirty_paths
        )
    return tuple(sorted(overlaps, key=lambda item: (item.path, item.foreign_intent_id)))


def _dirty_paths_from_porcelain(output: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in output.splitlines():
        if len(line) < 3:
            continue
        entry = line[3:].strip()
        if not entry:
            continue
        if " -> " in entry:
            old_path, new_path = entry.split(" -> ", 1)
            paths.add(_normalize_path(old_path))
            paths.add(_normalize_path(new_path))
            continue
        paths.add(_normalize_path(entry))
    return tuple(sorted(paths))


def _git_available(root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return completed.stdout.strip().lower() == "true"


def _normalize_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("/")
    if cleaned == ".":
        return ""
    if ".." in Path(cleaned).parts:
        from .messages import errors as err_msgs

        raise ValueError(err_msgs.PATH_TRAVERSAL.format(path=path))
    return cleaned


def _path_in_scope(path: str, scope_paths: set[str]) -> bool:
    return any(
        path == candidate or path.startswith(f"{candidate}/")
        for candidate in scope_paths
    )


def _bounded_sample(
    paths: Sequence[str],
    *,
    limit: int = _DIRTY_SUMMARY_SAMPLE_LIMIT,
) -> tuple[tuple[str, ...], bool]:
    if len(paths) <= limit:
        return tuple(paths), False
    return tuple(paths[:limit]), True


def hygiene_blocks_start_edit(
    hygiene: WorkspaceHygieneResult,
    *,
    dirty_scope_policy: str,
) -> bool:
    """Return whether scoped hygiene blocks edit permission at start."""
    return hygiene.blocks_edit and not (
        dirty_scope_policy == DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP
        and not hygiene.foreign_dirty_overlaps
    )


__all__ = [
    "DIRTY_SCOPE_POLICY_BLOCK",
    "DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP",
    "VALID_DIRTY_SCOPE_POLICIES",
    "DirtyPathsResult",
    "ForeignDirtyOverlap",
    "WorkspaceHygieneResult",
    "collect_dirty_paths",
    "evaluate_scoped_hygiene",
    "finish_hygiene_check",
    "hygiene_blocks_start_edit",
    "workspace_dirty_summary",
]
