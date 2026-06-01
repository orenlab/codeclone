# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from codeclone.surfaces.mcp import _workspace_hygiene as hygiene_mod
from codeclone.surfaces.mcp._workspace_hygiene import (
    DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP,
    DirtySnapshot,
    DirtySnapshotEntry,
    ForeignDirtyOverlap,
    WorkspaceHygieneResult,
    collect_dirty_paths,
    collect_dirty_snapshot,
    dirty_snapshot_from_payload,
    evaluate_scoped_hygiene,
    finish_hygiene_check,
    workspace_dirty_summary,
)
from codeclone.surfaces.mcp._workspace_intent_registry_lock import (
    WorkspaceRegistryLockError,
    workspace_registry_lock,
)
from codeclone.surfaces.mcp._workspace_intent_store import get_workspace_intent_store
from codeclone.surfaces.mcp._workspace_intents import (
    write_workspace_intent,
)
from tests.test_workspace_intents import _record

_GIT_RUN = "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run"


@contextmanager
def _mock_git_porcelain(
    porcelain: str,
    *,
    git_available: bool = True,
    git_side_effect: BaseException | None = None,
) -> Iterator[None]:
    git_run_patch = (
        patch(_GIT_RUN, side_effect=git_side_effect)
        if git_side_effect is not None
        else patch(
            _GIT_RUN,
            return_value=subprocess.CompletedProcess(
                args=["git"],
                returncode=0,
                stdout=porcelain,
                stderr="",
            ),
        )
    )
    with (
        patch.object(hygiene_mod, "_git_available", return_value=git_available),
        git_run_patch,
    ):
        yield


def test_foreign_dirty_overlap_to_payload() -> None:
    overlap = ForeignDirtyOverlap(
        path="pkg/a.py",
        foreign_intent_id="intent-foreign-001",
        foreign_persisted_status="active",
        foreign_ownership="foreign_active",
        foreign_agent_label="other",
        message="overlap",
    )
    payload = overlap.to_payload()
    assert payload["foreign_intent_id"] == "intent-foreign-001"
    assert payload["path"] == "pkg/a.py"


def test_workspace_hygiene_result_to_payload_includes_finish_fields() -> None:
    hygiene = WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=("pkg/a.py",),
        dirty_paths_in_scope=("pkg/a.py",),
        dirty_paths_outside_scope=(),
        foreign_dirty_overlaps=(),
        blocks_edit=True,
        unacknowledged_dirty_in_scope=("pkg/a.py",),
        blocks_finish=True,
    )
    payload = hygiene.to_payload()
    assert payload["blocks_finish"] is True
    assert payload["unacknowledged_dirty_in_scope"] == ["pkg/a.py"]


def test_collect_dirty_paths_when_git_unavailable(tmp_path: Path) -> None:
    with patch.object(hygiene_mod, "_git_available", return_value=False):
        result = collect_dirty_paths(tmp_path)
    assert result.git_available is False
    assert result.dirty_paths == ()


def test_collect_dirty_paths_git_failure_returns_unavailable(tmp_path: Path) -> None:
    with _mock_git_porcelain(
        "",
        git_side_effect=subprocess.TimeoutExpired("git", 30),
    ):
        result = collect_dirty_paths(tmp_path)
    assert result.git_available is False
    assert result.dirty_paths == ()


def test_collect_dirty_paths_scoped_filter() -> None:
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/b.py\n"):
        result = collect_dirty_paths(
            Path("/tmp/root"),
            scoped_paths=["pkg/a.py"],
        )
    assert result.git_available is True
    assert result.dirty_paths == ("pkg/a.py",)


def test_collect_dirty_snapshot_roundtrip() -> None:
    with _mock_git_porcelain(" M pkg/a.py\n"):
        snapshot = collect_dirty_snapshot(Path("/tmp/root"))
    assert snapshot.git_available is True
    assert snapshot.paths == ("pkg/a.py",)
    assert dirty_snapshot_from_payload(snapshot.to_payload()) == snapshot


def test_workspace_dirty_summary_without_git(tmp_path: Path) -> None:
    with patch.object(hygiene_mod, "_git_available", return_value=False):
        summary = workspace_dirty_summary(root=tmp_path)
    assert summary["git_available"] is False
    assert summary["dirty_paths_count"] == 0


def test_workspace_dirty_summary_truncates_sample() -> None:
    dirty_paths = tuple(f"pkg/file_{index}.py" for index in range(12))
    with patch.object(
        hygiene_mod,
        "collect_dirty_paths",
        return_value=hygiene_mod.DirtyPathsResult(
            git_available=True,
            dirty_paths=dirty_paths,
        ),
    ):
        summary = workspace_dirty_summary(root=Path("/tmp/root"))
    assert summary["dirty_paths_count"] == 12
    assert summary["sample_truncated"] is True
    assert len(cast(list[str], summary["dirty_paths_sample"])) == 10


def test_evaluate_scoped_hygiene_without_git(tmp_path: Path) -> None:
    store = get_workspace_intent_store(tmp_path)
    with patch.object(hygiene_mod, "_git_available", return_value=False):
        hygiene = evaluate_scoped_hygiene(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            store=store,
            own_pid=os.getpid(),
            own_start_epoch=100,
        )
    assert hygiene.git_available is False
    assert hygiene.blocks_edit is False


def test_finish_hygiene_check_blocks_unacknowledged_dirty(tmp_path: Path) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/b.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=["pkg/b.py"],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.unacknowledged_dirty_in_scope == ("pkg/b.py",)
    assert hygiene.blocks_finish is True
    assert hygiene.finish_block_reason == "missing_evidence"


def test_finish_hygiene_check_allows_preexisting_unscoped_dirty(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/extra.py\n"):
        snapshot = collect_dirty_snapshot(tmp_path)
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
            start_dirty_snapshot=snapshot,
        )
    assert hygiene.preexisting_unscoped_dirty == ("pkg/extra.py",)
    assert hygiene.unattributed_unscoped_dirty == ()
    assert hygiene.blocks_finish is False


def test_finish_hygiene_check_blocks_new_unattributed_unscoped_dirty(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    start_snapshot = DirtySnapshot(
        git_available=True,
        captured_at_utc="2026-01-01T00:00:00Z",
        entries=(
            DirtySnapshotEntry(
                path="pkg/a.py",
                status_xy=" M",
                digest="start-a",
                digest_status="ok",
            ),
        ),
    )
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/extra.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
            start_dirty_snapshot=start_snapshot,
        )
    assert hygiene.new_unattributed_unscoped_dirty == ("pkg/extra.py",)
    assert hygiene.unattributed_unscoped_dirty == ("pkg/extra.py",)
    assert hygiene.blocks_finish is True
    assert hygiene.finish_block_reason == "new_unattributed_unscoped_dirty"


def test_finish_hygiene_check_legacy_snapshot_blocks_unknown_unscoped_dirty(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/extra.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.unknown_unattributed_unscoped_dirty == ("pkg/extra.py",)
    assert hygiene.dirty_snapshot_status == "missing_legacy_conservative"
    assert hygiene.blocks_finish is True
    assert hygiene.finish_block_reason == "unknown_unattributed_unscoped_dirty"


def test_finish_hygiene_check_blocks_modified_unattributed_unscoped_dirty(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    start_snapshot = DirtySnapshot(
        git_available=True,
        captured_at_utc="2026-01-01T00:00:00Z",
        entries=(
            DirtySnapshotEntry(
                path="pkg/extra.py",
                status_xy=" M",
                digest="old-digest",
                digest_status="ok",
            ),
        ),
    )
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/extra.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
            start_dirty_snapshot=start_snapshot,
        )
    assert hygiene.modified_unattributed_unscoped_dirty == ("pkg/extra.py",)
    assert hygiene.blocks_finish is True
    assert hygiene.finish_block_reason == "modified_unattributed_unscoped_dirty"


def test_finish_hygiene_check_ignores_foreign_unscoped_dirty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_pid = 33333
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda pid: pid == live_pid,
    )
    foreign = _record(
        intent_id="intent-foreign-other-001",
        pid=live_pid,
        start_epoch=300,
        scope={
            "allowed_files": ["pkg/foreign.py"],
            "allowed_related": [],
            "forbidden": [],
        },
    )
    assert write_workspace_intent(root=tmp_path, record=foreign)
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n M pkg/foreign.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.foreign_attributed_outside_scope == ("pkg/foreign.py",)
    assert hygiene.own_unscoped_dirty == ()
    assert hygiene.blocks_finish is False


def test_finish_hygiene_check_blocks_unacknowledged_dirty_legacy(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=[],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.unacknowledged_dirty_in_scope == ("pkg/a.py",)
    assert hygiene.blocks_finish is True


def test_finish_hygiene_check_blocks_on_foreign_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_pid = 33333
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda pid: pid == live_pid,
    )
    foreign = _record(
        intent_id="intent-foreign-dirty-001",
        pid=live_pid,
        start_epoch=300,
    )
    assert write_workspace_intent(root=tmp_path, record=foreign)
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n"):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.blocks_finish is True
    assert len(hygiene.foreign_dirty_overlaps) == 1


def test_dirty_paths_from_porcelain_skips_short_and_parses_renames() -> None:
    dirty = hygiene_mod._dirty_paths_from_porcelain(
        "ab\n   \n M pkg/a.py\nR  pkg/old.py -> pkg/new.py\n"
    )
    assert dirty == ("pkg/a.py", "pkg/new.py", "pkg/old.py")


def test_normalize_path_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="path traversal"):
        hygiene_mod._normalize_path("../etc/passwd")


def test_normalize_path_strips_dot_slash_prefix() -> None:
    assert hygiene_mod._normalize_path("./pkg/a.py") == "pkg/a.py"


def test_normalize_path_dot_returns_empty() -> None:
    assert hygiene_mod._normalize_path(".") == ""


@pytest.mark.parametrize(
    ("intent_id", "own_pid", "own_start_epoch", "own_intent_id"),
    [
        ("intent-own-001", 99999, 999, "intent-own-001"),
        ("intent-own-002", 11111, 100, None),
    ],
)
def test_foreign_dirty_overlaps_skip_own_identity(
    tmp_path: Path,
    intent_id: str,
    own_pid: int,
    own_start_epoch: int,
    own_intent_id: str | None,
) -> None:
    own = _record(intent_id=intent_id, pid=11111, start_epoch=100)
    assert write_workspace_intent(root=tmp_path, record=own)
    store = get_workspace_intent_store(tmp_path)
    overlaps = hygiene_mod._foreign_dirty_overlaps(
        dirty_paths=["pkg/a.py"],
        store=store,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        own_intent_id=own_intent_id,
    )
    assert overlaps == ()


def test_registry_lock_retries_until_acquired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / ".cache" / "codeclone" / "intents" / ".lock"
    attempts = iter([BlockingIOError(), None])

    def _acquire_once(handle: object) -> None:
        result = next(attempts, None)
        if result is not None:
            raise result

    times = iter([0.0, 0.05, 0.1])
    monkeypatch.setattr(
        "codeclone.utils.file_lock.time.monotonic",
        lambda: next(times),
    )
    monkeypatch.setattr(
        "codeclone.utils.file_lock._acquire_exclusive_lock",
        _acquire_once,
    )
    with workspace_registry_lock(lock_path, timeout_seconds=1.0):
        assert lock_path.is_file()


def test_registry_lock_timeout_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / ".cache" / "codeclone" / "intents" / ".lock"
    times = iter([0.0, 10.0])

    def _always_busy(handle: object) -> None:
        raise BlockingIOError

    monkeypatch.setattr(
        "codeclone.utils.file_lock.time.monotonic",
        lambda: next(times),
    )
    monkeypatch.setattr(
        "codeclone.utils.file_lock._acquire_exclusive_lock",
        _always_busy,
    )
    with (
        pytest.raises(WorkspaceRegistryLockError, match="Timed out"),
        workspace_registry_lock(lock_path, timeout_seconds=1.0),
    ):
        pass


def test_evaluate_scoped_hygiene_includes_related_scope(tmp_path: Path) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M tests/test_a.py\n"):
        hygiene = evaluate_scoped_hygiene(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=["tests/test_a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
        )
    assert hygiene.dirty_paths == ("tests/test_a.py",)
    assert hygiene.dirty_paths_outside_scope == ("tests/test_a.py",)
    assert hygiene.blocks_edit is False


def test_foreign_dirty_overlaps_skip_terminal_foreign(
    tmp_path: Path,
) -> None:
    terminal = replace(_record(intent_id="intent-clean-001"), status="clean")
    assert write_workspace_intent(root=tmp_path, record=terminal)
    store = get_workspace_intent_store(tmp_path)
    overlaps = hygiene_mod._foreign_dirty_overlaps(
        dirty_paths=["pkg/a.py"],
        store=store,
        own_pid=22222,
        own_start_epoch=400,
        own_intent_id=None,
    )
    assert overlaps == ()


def test_evaluate_scoped_hygiene_marks_dirty_in_blocking_scope(tmp_path: Path) -> None:
    store = get_workspace_intent_store(tmp_path)
    with _mock_git_porcelain(" M pkg/a.py\n"):
        hygiene = evaluate_scoped_hygiene(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
        )
    assert hygiene.dirty_paths_in_scope == ("pkg/a.py",)
    assert hygiene.dirty_paths_outside_scope == ()
    assert hygiene.blocks_edit is True


def test_finish_hygiene_check_returns_early_when_git_unavailable(
    tmp_path: Path,
) -> None:
    store = get_workspace_intent_store(tmp_path)
    with patch.object(hygiene_mod, "_git_available", return_value=False):
        hygiene = finish_hygiene_check(
            root=tmp_path,
            allowed_files=["pkg/a.py"],
            allowed_related=[],
            resolved_files=["pkg/a.py"],
            store=store,
            own_pid=22222,
            own_start_epoch=400,
            own_intent_id="intent-own-001",
        )
    assert hygiene.git_available is False
    assert hygiene.blocks_finish is False


def test_registry_lock_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / ".cache" / "codeclone" / "intents" / ".lock"
    with workspace_registry_lock(lock_path):
        assert lock_path.is_file()


def test_continue_own_wip_policy_allows_own_dirty_without_foreign() -> None:
    hygiene = WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=("pkg/a.py",),
        dirty_paths_in_scope=("pkg/a.py",),
        dirty_paths_outside_scope=(),
        foreign_dirty_overlaps=(),
        blocks_edit=True,
    )
    assert (
        hygiene_mod.hygiene_blocks_start_edit(
            hygiene,
            dirty_scope_policy=DIRTY_SCOPE_POLICY_CONTINUE_OWN_WIP,
        )
        is False
    )
