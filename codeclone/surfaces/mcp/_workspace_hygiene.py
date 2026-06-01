# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Git working-tree hygiene evaluation for workspace change control."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterator, Sequence
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
    WorkspaceIntentRecord,
    _scope_all_sets,
    classify_intent_ownership,
    format_utc,
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
class DirtySnapshotEntry:
    path: str
    status_xy: str
    digest: str | None
    digest_status: str

    def to_payload(self) -> dict[str, object]:
        return {
            "status_xy": self.status_xy,
            "digest": self.digest,
            "digest_status": self.digest_status,
        }


@dataclass(frozen=True, slots=True)
class DirtySnapshot:
    git_available: bool
    captured_at_utc: str
    entries: tuple[DirtySnapshotEntry, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)

    def entry_map(self) -> dict[str, DirtySnapshotEntry]:
        return {entry.path: entry for entry in self.entries}

    def to_payload(self) -> dict[str, object]:
        return {
            "git_available": self.git_available,
            "captured_at_utc": self.captured_at_utc,
            "entries": {
                entry.path: entry.to_payload()
                for entry in sorted(self.entries, key=lambda item: item.path)
            },
        }

    def summary_payload(self) -> dict[str, object]:
        digest_counts: dict[str, int] = {}
        for entry in self.entries:
            digest_counts[entry.digest_status] = (
                digest_counts.get(
                    entry.digest_status,
                    0,
                )
                + 1
            )
        return {
            "git_available": self.git_available,
            "captured_at_utc": self.captured_at_utc,
            "paths_count": len(self.entries),
            "digest_status_counts": dict(sorted(digest_counts.items())),
        }


@dataclass(frozen=True, slots=True)
class DirtyAttribution:
    path: str
    scope_relation: str
    evidence: str
    start_state: str
    intent_attribution: str
    classification: str
    blocking: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "scope_relation": self.scope_relation,
            "evidence": self.evidence,
            "start_state": self.start_state,
            "intent_attribution": self.intent_attribution,
            "classification": self.classification,
            "blocking": self.blocking,
        }


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
    own_unscoped_dirty: tuple[str, ...] = ()
    unattributed_unscoped_dirty: tuple[str, ...] = ()
    preexisting_unscoped_dirty: tuple[str, ...] = ()
    new_unattributed_unscoped_dirty: tuple[str, ...] = ()
    modified_unattributed_unscoped_dirty: tuple[str, ...] = ()
    unknown_unattributed_unscoped_dirty: tuple[str, ...] = ()
    foreign_attributed_outside_scope: tuple[str, ...] = ()
    dirty_attribution: tuple[DirtyAttribution, ...] = ()
    dirty_snapshot: DirtySnapshot | None = None
    dirty_snapshot_status: str | None = None
    files_for_scope_check: tuple[str, ...] = ()
    blocks_finish: bool = False
    finish_block_reason: str | None = None

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
        if self.own_unscoped_dirty:
            payload["own_unscoped_dirty"] = list(self.own_unscoped_dirty)
        if self.unattributed_unscoped_dirty:
            payload["unattributed_unscoped_dirty"] = list(
                self.unattributed_unscoped_dirty
            )
        if self.preexisting_unscoped_dirty:
            payload["preexisting_unscoped_dirty"] = list(
                self.preexisting_unscoped_dirty
            )
        if self.new_unattributed_unscoped_dirty:
            payload["new_unattributed_unscoped_dirty"] = list(
                self.new_unattributed_unscoped_dirty
            )
        if self.modified_unattributed_unscoped_dirty:
            payload["modified_unattributed_unscoped_dirty"] = list(
                self.modified_unattributed_unscoped_dirty
            )
        if self.unknown_unattributed_unscoped_dirty:
            payload["unknown_unattributed_unscoped_dirty"] = list(
                self.unknown_unattributed_unscoped_dirty
            )
        if self.foreign_attributed_outside_scope:
            payload["foreign_attributed_outside_scope"] = list(
                self.foreign_attributed_outside_scope
            )
        if self.dirty_attribution:
            payload["dirty_attribution"] = [
                item.to_payload() for item in self.dirty_attribution
            ]
        if self.dirty_snapshot is not None:
            payload["dirty_snapshot"] = self.dirty_snapshot.summary_payload()
        if self.dirty_snapshot_status is not None:
            payload["dirty_snapshot_status"] = self.dirty_snapshot_status
        if self.files_for_scope_check:
            payload["files_for_scope_check"] = list(self.files_for_scope_check)
        if self.blocks_finish:
            payload["blocks_finish"] = True
        if self.finish_block_reason is not None:
            payload["finish_block_reason"] = self.finish_block_reason
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


def collect_dirty_snapshot(root: Path) -> DirtySnapshot:
    """Collect full git dirty state with stable per-path digests when available."""
    captured_at = format_utc(utc_now())
    if not _git_available(root):
        return DirtySnapshot(
            git_available=False,
            captured_at_utc=captured_at,
            entries=(),
        )
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return DirtySnapshot(
            git_available=False,
            captured_at_utc=captured_at,
            entries=(),
        )
    entries = tuple(
        DirtySnapshotEntry(
            path=path,
            status_xy=status_xy,
            digest=digest,
            digest_status=digest_status,
        )
        for path, status_xy in _dirty_entries_from_porcelain(completed.stdout)
        for digest, digest_status in (_dirty_entry_digest(root, path, status_xy),)
    )
    return DirtySnapshot(
        git_available=True,
        captured_at_utc=captured_at,
        entries=tuple(sorted(entries, key=lambda entry: entry.path)),
    )


def dirty_snapshot_from_payload(payload: object) -> DirtySnapshot | None:
    """Decode a stored dirty snapshot. Invalid legacy/corrupt data is ignored."""
    if not isinstance(payload, dict):
        return None
    git_available = payload.get("git_available")
    captured_at = payload.get("captured_at_utc")
    raw_entries = payload.get("entries")
    if not isinstance(git_available, bool) or not isinstance(captured_at, str):
        return None
    if not isinstance(raw_entries, dict):
        return None
    entries: list[DirtySnapshotEntry] = []
    for raw_path, raw_entry in raw_entries.items():
        if not isinstance(raw_path, str) or not isinstance(raw_entry, dict):
            return None
        try:
            path = _normalize_path(raw_path)
        except ValueError:
            return None
        status_xy = raw_entry.get("status_xy")
        digest = raw_entry.get("digest")
        digest_status = raw_entry.get("digest_status")
        if not isinstance(status_xy, str) or not isinstance(digest_status, str):
            return None
        if digest is not None and not isinstance(digest, str):
            return None
        entries.append(
            DirtySnapshotEntry(
                path=path,
                status_xy=status_xy[:2].ljust(2),
                digest=digest,
                digest_status=digest_status,
            )
        )
    return DirtySnapshot(
        git_available=git_available,
        captured_at_utc=captured_at,
        entries=tuple(sorted(entries, key=lambda entry: entry.path)),
    )


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


def _declared_scope_sets(
    allowed_files: Sequence[str],
    allowed_related: Sequence[str] | None,
) -> tuple[set[str], set[str], set[str]]:
    blocking_scope = {_normalize_path(path) for path in allowed_files if path.strip()}
    related_scope = {
        _normalize_path(path) for path in (allowed_related or ()) if path.strip()
    } - blocking_scope
    return blocking_scope, related_scope, blocking_scope | related_scope


def _iter_foreign_intent_scope_matches(
    *,
    dirty_paths: Sequence[str],
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> Iterator[tuple[WorkspaceIntentRecord, str, tuple[str, ...]]]:
    if not dirty_paths:
        return
    now = utc_now()
    for record in store.list_records_for_hygiene():
        if _skip_foreign_dirty_record(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            own_intent_id=own_intent_id,
        ):
            continue
        foreign_allowed, _, _ = _scope_all_sets(record.scope)
        ownership = classify_intent_ownership(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            now=now,
        )
        if ownership not in _FOREIGN_DIRTY_OWNERSHIP:
            continue
        matched = tuple(
            sorted(
                path for path in dirty_paths if _path_in_scope(path, foreign_allowed)
            )
        )
        if matched:
            yield record, ownership.value, matched


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
    blocking_scope, _, evaluation_scope = _declared_scope_sets(
        allowed_files,
        allowed_related,
    )
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
    start_dirty_snapshot: DirtySnapshot | None = None,
) -> WorkspaceHygieneResult:
    """Finish-time hygiene gate against declared scope and git evidence."""
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
    current_snapshot = collect_dirty_snapshot(root)
    if not current_snapshot.git_available:
        return hygiene
    all_dirty_paths = current_snapshot.paths
    evidence = {_normalize_path(path) for path in resolved_files if path.strip()}
    blocking_scope, related_scope, declared_scope = _declared_scope_sets(
        allowed_files,
        allowed_related,
    )
    dirty_in_declared = tuple(
        sorted(path for path in all_dirty_paths if _path_in_scope(path, declared_scope))
    )
    dirty_outside_declared = tuple(
        sorted(
            path for path in all_dirty_paths if not _path_in_scope(path, declared_scope)
        )
    )
    foreign_attributed_outside = _foreign_attributed_dirty_paths(
        dirty_paths=dirty_outside_declared,
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    )
    attribution = _dirty_attribution(
        dirty_paths=all_dirty_paths,
        evidence=evidence,
        blocking_scope=blocking_scope,
        related_scope=related_scope,
        declared_scope=declared_scope,
        current_snapshot=current_snapshot,
        start_dirty_snapshot=start_dirty_snapshot,
        foreign_attributed_outside=foreign_attributed_outside,
    )
    new_unattributed = _classified_paths(attribution, "new_unattributed_unscoped_dirty")
    modified_unattributed = _classified_paths(
        attribution,
        "modified_unattributed_unscoped_dirty",
    )
    unknown_unattributed = _classified_paths(
        attribution,
        "unknown_unattributed_unscoped_dirty",
    )
    preexisting_unscoped = _classified_paths(attribution, "preexisting_unscoped_dirty")
    unattributed_unscoped = tuple(
        sorted(new_unattributed + modified_unattributed + unknown_unattributed)
    )
    unacknowledged = tuple(sorted(set(dirty_in_declared) - evidence))
    files_for_scope_check = tuple(sorted(evidence | set(unattributed_unscoped)))
    blocks_finish = False
    finish_block_reason: str | None = None
    if unacknowledged:
        blocks_finish = True
        finish_block_reason = "missing_evidence"
    elif new_unattributed:
        blocks_finish = True
        finish_block_reason = "new_unattributed_unscoped_dirty"
    elif modified_unattributed:
        blocks_finish = True
        finish_block_reason = "modified_unattributed_unscoped_dirty"
    elif unknown_unattributed:
        blocks_finish = True
        finish_block_reason = "unknown_unattributed_unscoped_dirty"
    elif hygiene.foreign_dirty_overlaps:
        blocks_finish = True
        finish_block_reason = "foreign_dirty_overlap"
    return WorkspaceHygieneResult(
        git_available=hygiene.git_available,
        dirty_paths=all_dirty_paths,
        dirty_paths_in_scope=dirty_in_declared,
        dirty_paths_outside_scope=dirty_outside_declared,
        foreign_dirty_overlaps=hygiene.foreign_dirty_overlaps,
        blocks_edit=hygiene.blocks_edit,
        unacknowledged_dirty_in_scope=unacknowledged,
        # Legacy alias retained for one contract cycle. These paths are
        # unattributed, not proven to be owned by the current agent.
        own_unscoped_dirty=unattributed_unscoped,
        unattributed_unscoped_dirty=unattributed_unscoped,
        preexisting_unscoped_dirty=preexisting_unscoped,
        new_unattributed_unscoped_dirty=new_unattributed,
        modified_unattributed_unscoped_dirty=modified_unattributed,
        unknown_unattributed_unscoped_dirty=unknown_unattributed,
        foreign_attributed_outside_scope=tuple(sorted(foreign_attributed_outside)),
        dirty_attribution=attribution,
        dirty_snapshot=current_snapshot,
        dirty_snapshot_status=_snapshot_status(start_dirty_snapshot),
        files_for_scope_check=files_for_scope_check,
        blocks_finish=blocks_finish,
        finish_block_reason=finish_block_reason,
    )


def _dirty_attribution(
    *,
    dirty_paths: Sequence[str],
    evidence: set[str],
    blocking_scope: set[str],
    related_scope: set[str],
    declared_scope: set[str],
    current_snapshot: DirtySnapshot,
    start_dirty_snapshot: DirtySnapshot | None,
    foreign_attributed_outside: frozenset[str],
) -> tuple[DirtyAttribution, ...]:
    current_entries = current_snapshot.entry_map()
    start_entries = (
        start_dirty_snapshot.entry_map() if start_dirty_snapshot is not None else {}
    )
    items: list[DirtyAttribution] = []
    for path in sorted(dirty_paths):
        scope_relation = _scope_relation(
            path,
            blocking_scope=blocking_scope,
            related_scope=related_scope,
            declared_scope=declared_scope,
        )
        evidence_state = "present" if path in evidence else "absent"
        start_state = _dirty_start_state(
            current_entries.get(path),
            start_entries.get(path),
            snapshot=start_dirty_snapshot,
        )
        intent_attribution = (
            "foreign_active_or_stale" if path in foreign_attributed_outside else "none"
        )
        classification, blocking = _dirty_classification(
            scope_relation=scope_relation,
            evidence_state=evidence_state,
            start_state=start_state,
            intent_attribution=intent_attribution,
        )
        items.append(
            DirtyAttribution(
                path=path,
                scope_relation=scope_relation,
                evidence=evidence_state,
                start_state=start_state,
                intent_attribution=intent_attribution,
                classification=classification,
                blocking=blocking,
            )
        )
    return tuple(items)


def _scope_relation(
    path: str,
    *,
    blocking_scope: set[str],
    related_scope: set[str],
    declared_scope: set[str],
) -> str:
    if _path_in_scope(path, blocking_scope):
        return "own_allowed"
    if _path_in_scope(path, related_scope):
        return "own_related"
    if _path_in_scope(path, declared_scope):
        return "declared"
    return "outside"


def _dirty_start_state(
    current: DirtySnapshotEntry | None,
    start: DirtySnapshotEntry | None,
    *,
    snapshot: DirtySnapshot | None,
) -> str:
    if snapshot is None:
        return "unknown"
    if start is None:
        return "absent"
    if current is None:
        return "cleaned"
    if start.digest_status != "ok" or current.digest_status != "ok":
        return "unknown"
    if start.digest == current.digest and start.status_xy == current.status_xy:
        return "present_same"
    return "present_changed"


def _dirty_classification(
    *,
    scope_relation: str,
    evidence_state: str,
    start_state: str,
    intent_attribution: str,
) -> tuple[str, bool]:
    if scope_relation != "outside":
        if evidence_state == "absent":
            return "missing_evidence", True
        return "declared_scope_dirty", False
    if intent_attribution == "foreign_active_or_stale":
        return "foreign_attributed_outside_scope", False
    if start_state == "present_same":
        return "preexisting_unscoped_dirty", False
    if start_state == "absent":
        return "new_unattributed_unscoped_dirty", True
    if start_state == "present_changed":
        return "modified_unattributed_unscoped_dirty", True
    return "unknown_unattributed_unscoped_dirty", True


def _classified_paths(
    attribution: Sequence[DirtyAttribution],
    classification: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.path for item in attribution if item.classification == classification
        )
    )


def _snapshot_status(snapshot: DirtySnapshot | None) -> str:
    if snapshot is None:
        return "missing_legacy_conservative"
    if not snapshot.git_available:
        return "git_unavailable"
    return "available"


def _skip_foreign_dirty_record(
    record: WorkspaceIntentRecord,
    *,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> bool:
    if (
        record.agent_pid == own_pid and record.agent_start_epoch == own_start_epoch
    ) or (own_intent_id is not None and record.intent_id == own_intent_id):
        return True
    if is_terminal_workspace_intent_status(record.status):
        return True
    return record.status == WorkspaceIntentStatus.QUEUED.value


def _foreign_attributed_dirty_paths(
    *,
    dirty_paths: Sequence[str],
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> frozenset[str]:
    """Dirty paths outside own scope that belong to a foreign active/stale intent."""
    attributed: set[str] = set()
    for _record, _ownership, matched in _iter_foreign_intent_scope_matches(
        dirty_paths=dirty_paths,
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    ):
        attributed.update(matched)
    return frozenset(attributed)


def _foreign_dirty_overlaps(
    *,
    dirty_paths: Sequence[str],
    store: WorkspaceIntentStore,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> tuple[ForeignDirtyOverlap, ...]:
    overlaps: list[ForeignDirtyOverlap] = []
    for record, ownership, matched in _iter_foreign_intent_scope_matches(
        dirty_paths=dirty_paths,
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    ):
        overlaps.extend(
            ForeignDirtyOverlap(
                path=path,
                foreign_intent_id=record.intent_id,
                foreign_persisted_status=record.status,
                foreign_ownership=ownership,
                foreign_agent_label=record.agent_label,
                message=(
                    f"{_BASE_DIRTY_SCOPE_MESSAGE} Foreign intent "
                    f"{record.intent_id} previously declared this path."
                ),
            )
            for path in matched
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


def _dirty_entries_from_porcelain(output: str) -> tuple[tuple[str, str], ...]:
    entries: dict[str, str] = {}
    for line in output.splitlines():
        if len(line) < 3:
            continue
        status_xy = line[:2]
        entry = line[3:].strip()
        if not entry:
            continue
        if " -> " in entry:
            old_path, new_path = entry.split(" -> ", 1)
            entries[_normalize_path(old_path)] = status_xy
            entries[_normalize_path(new_path)] = status_xy
            continue
        entries[_normalize_path(entry)] = status_xy
    return tuple(sorted(entries.items()))


def _dirty_entry_digest(
    root: Path,
    path: str,
    status_xy: str,
) -> tuple[str | None, str]:
    """Return a stable digest for the dirty content, or mark it unavailable."""
    if status_xy == "??":
        return _untracked_file_digest(root, path)
    cached = _git_diff_bytes(root, ["diff", "--cached", "--binary", "--", path])
    worktree = _git_diff_bytes(root, ["diff", "--binary", "--", path])
    if cached is None or worktree is None:
        return None, "unavailable"
    digest = hashlib.sha256()
    digest.update(status_xy.encode("utf-8", "surrogateescape"))
    digest.update(b"\0")
    digest.update(path.encode("utf-8", "surrogateescape"))
    digest.update(b"\0cached\0")
    digest.update(cached)
    digest.update(b"\0worktree\0")
    digest.update(worktree)
    return digest.hexdigest(), "ok"


def _git_diff_bytes(root: Path, args: Sequence[str]) -> bytes | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    stdout = completed.stdout
    if isinstance(stdout, bytes):
        return stdout
    if isinstance(stdout, str):
        return stdout.encode("utf-8", "surrogateescape")
    return None


def _untracked_file_digest(root: Path, path: str) -> tuple[str | None, str]:
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None, "unavailable"
    if not target.is_file():
        return None, "unavailable"
    digest = hashlib.sha256()
    digest.update(b"untracked\0")
    digest.update(path.encode("utf-8", "surrogateescape"))
    digest.update(b"\0")
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None, "unavailable"
    return digest.hexdigest(), "ok"


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
    "DirtyAttribution",
    "DirtyPathsResult",
    "DirtySnapshot",
    "DirtySnapshotEntry",
    "ForeignDirtyOverlap",
    "WorkspaceHygieneResult",
    "collect_dirty_paths",
    "collect_dirty_snapshot",
    "dirty_snapshot_from_payload",
    "evaluate_scoped_hygiene",
    "finish_hygiene_check",
    "hygiene_blocks_start_edit",
    "workspace_dirty_summary",
]
