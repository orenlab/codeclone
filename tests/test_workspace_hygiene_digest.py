# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.api.workspace import (
    WorkspaceDirtyPathsDTO,
    WorkspaceDirtySnapshotDTO,
    collect_workspace_dirty_snapshot,
)
from codeclone.surfaces.mcp._workspace_hygiene import (
    DirtyAttribution,
    DirtySnapshot,
    DirtySnapshotEntry,
    WorkspaceHygieneResult,
    _dirty_start_state,
    _scope_relation,
    _snapshot_status,
    collect_dirty_paths,
    collect_dirty_snapshot,
    dirty_snapshot_from_payload,
    finish_hygiene_check,
)
from codeclone.surfaces.mcp._workspace_intent_store import get_workspace_intent_store


def test_dirty_snapshot_to_payload_sorts_entries() -> None:
    snapshot = DirtySnapshot(
        git_available=True,
        captured_at_utc="2026-01-01T00:00:00Z",
        entries=(
            DirtySnapshotEntry(
                path="b.py",
                status_xy=" M",
                digest_status="ok",
                digest="aa",
            ),
            DirtySnapshotEntry(
                path="a.py",
                status_xy=" M",
                digest_status="ok",
                digest="bb",
            ),
        ),
    )
    payload = snapshot.to_payload()
    entries_obj = payload["entries"]
    assert isinstance(entries_obj, dict)
    assert list(entries_obj.keys()) == ["a.py", "b.py"]


def test_untracked_file_digest_reads_file_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "pkg"
    target.mkdir()
    sample = target / "mod.py"
    sample.write_text("print('ok')\n", encoding="utf-8")

    with (
        patch(
            "codeclone.paths.git_snapshot.git_repository_available",
            return_value=True,
        ),
        patch(
            "codeclone.paths.git_snapshot._run_git_text",
            return_value="?? pkg/mod.py\n",
        ),
    ):
        projection = collect_workspace_dirty_snapshot(root=root)
    assert projection.entries[0].digest_status == "ok"
    assert projection.entries[0].digest is not None
    assert len(projection.entries[0].digest or "") == 64

    with (
        patch(
            "codeclone.paths.git_snapshot.git_repository_available",
            return_value=True,
        ),
        patch(
            "codeclone.paths.git_snapshot._run_git_text",
            return_value="?? ../escape.py\n",
        ),
    ):
        outside = collect_workspace_dirty_snapshot(root=root)
    assert outside.git_available is False
    assert outside.entries == ()


def test_git_diff_bytes_returns_none_on_failure(tmp_path: Path) -> None:
    with (
        patch(
            "codeclone.paths.git_snapshot.git_repository_available",
            return_value=True,
        ),
        patch(
            "codeclone.paths.git_snapshot._run_git_text",
            return_value=" M a.py\n",
        ),
        patch("codeclone.paths.git_snapshot.git_diff_bytes", return_value=None),
    ):
        result = collect_workspace_dirty_snapshot(root=tmp_path)
    assert result.entries[0].digest is None
    assert result.entries[0].digest_status == "unavailable"


def test_workspace_hygiene_payload_detail_and_snapshot_status() -> None:
    result = WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=("pkg/a.py",),
        dirty_paths_in_scope=("pkg/a.py",),
        dirty_paths_outside_scope=("tmp.log",),
        foreign_dirty_overlaps=(),
        blocks_edit=True,
        dirty_attribution=(
            DirtyAttribution(
                path="tmp.log",
                scope_relation="outside",
                evidence="absent",
                start_state="unknown",
                intent_attribution="none",
                classification="unknown_unattributed_unscoped_dirty",
                blocking=False,
            ),
        ),
        dirty_snapshot=DirtySnapshot(
            git_available=False,
            captured_at_utc="2026-01-01T00:00:00Z",
            entries=(),
        ),
        dirty_snapshot_status="git_unavailable",
        blocks_finish=True,
        finish_block_reason="missing_evidence",
    )
    payload = result.to_payload(detail_level="full")
    assert payload["blocks_finish"] is True
    assert payload["finish_block_reason"] == "missing_evidence"
    assert payload["dirty_snapshot_status"] == "git_unavailable"
    assert _snapshot_status(None) == "missing_legacy_conservative"
    assert _snapshot_status(result.dirty_snapshot) == "git_unavailable"


def test_workspace_door_handles_rename_and_blank_rows(tmp_path: Path) -> None:
    output = "\n".join(
        [
            "?? pkg/new.py",
            "R  pkg/old.py -> pkg/newer.py",
            " M   ",
            "x",
        ]
    )
    with (
        patch(
            "codeclone.paths.git_snapshot.git_repository_available",
            return_value=True,
        ),
        patch("codeclone.paths.git_snapshot._run_git_text", return_value=output),
        patch(
            "codeclone.paths.git_snapshot.dirty_entry_digest",
            return_value=("0" * 64, "ok"),
        ),
    ):
        projection = collect_workspace_dirty_snapshot(root=tmp_path)
    entries = {(entry.path, entry.status_xy) for entry in projection.entries}
    assert ("pkg/new.py", "??") in entries
    assert ("pkg/old.py", "R ") in entries
    assert ("pkg/newer.py", "R ") in entries


def test_workspace_door_projects_unavailable_dirty_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot.git_repository_available",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: " M pkg/a.py\n",
    )
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot.git_diff_bytes",
        lambda _root, args: b"cached" if "--cached" in args else None,
    )
    projection = collect_workspace_dirty_snapshot(root=tmp_path)
    assert projection.entries[0].digest is None
    assert projection.entries[0].digest_status == "unavailable"


def test_dirty_entry_digest_status_aware_skip_is_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contract lock: skipping the guaranteed-empty diff side (by porcelain XY)
    # must produce byte-identical digests, because real git returns b"" for the
    # clean side. The guaranteed-empty side must not be invoked at all.
    calls: list[list[str]] = []

    def _fake_diff(_root: Path, args: list[str]) -> bytes:
        calls.append(list(args))
        return b"CACHED" if "--cached" in args else b"WORKTREE"

    monkeypatch.setattr(
        "codeclone.paths.git_snapshot.git_repository_available",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot.git_diff_bytes",
        _fake_diff,
    )

    def _expected(status_xy: str, path: str, cached: bytes, worktree: bytes) -> str:
        digest = hashlib.sha256()
        digest.update(status_xy.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0cached\0")
        digest.update(cached)
        digest.update(b"\0worktree\0")
        digest.update(worktree)
        return digest.hexdigest()

    # Unstaged-only (" M"): X==' ' skips the cached side -> substitute b"".
    calls.clear()
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: " M pkg/a.py\n",
    )
    projection = collect_workspace_dirty_snapshot(root=tmp_path)
    digest = projection.entries[0].digest
    assert not any("--cached" in call for call in calls)
    assert digest == _expected(" M", "pkg/a.py", b"", b"WORKTREE")

    # Staged-only ("M "): Y==' ' skips the worktree side -> substitute b"".
    calls.clear()
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: "M  pkg/a.py\n",
    )
    projection = collect_workspace_dirty_snapshot(root=tmp_path)
    digest = projection.entries[0].digest
    assert calls and all("--cached" in call for call in calls)
    assert digest == _expected("M ", "pkg/a.py", b"CACHED", b"")

    # Both sides dirty ("MM"): neither side is skipped.
    calls.clear()
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: "MM pkg/a.py\n",
    )
    projection = collect_workspace_dirty_snapshot(root=tmp_path)
    digest = projection.entries[0].digest
    assert len(calls) == 2
    assert digest == _expected("MM", "pkg/a.py", b"CACHED", b"WORKTREE")


def test_untracked_digest_handles_missing_and_open_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot.git_repository_available",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: "?? pkg\n",
    )
    missing = collect_workspace_dirty_snapshot(root=root)
    assert missing.entries[0].digest is None
    assert missing.entries[0].digest_status == "unavailable"

    target = root / "pkg" / "broken.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    def _boom_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("read failed")

    monkeypatch.setattr(Path, "open", _boom_open)
    monkeypatch.setattr(
        "codeclone.paths.git_snapshot._run_git_text",
        lambda *_args, **_kwargs: "?? pkg/broken.py\n",
    )
    broken = collect_workspace_dirty_snapshot(root=root)
    assert broken.entries[0].digest is None
    assert broken.entries[0].digest_status == "unavailable"


def test_scope_relation_declared_branch() -> None:
    relation = _scope_relation(
        "docs/guide.md",
        blocking_scope={"pkg/"},
        related_scope={"tests/"},
        declared_scope={"docs/guide.md"},
    )
    assert relation == "declared"


def test_workspace_hygiene_snapshot_and_payload_edge_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.collect_workspace_dirty_snapshot",
        lambda **_kwargs: WorkspaceDirtySnapshotDTO(
            git_available=False,
            captured_at_utc="x",
            entries=(),
        ),
    )
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.collect_workspace_dirty_paths",
        lambda **_kwargs: WorkspaceDirtyPathsDTO(
            git_available=False,
            dirty_paths=(),
        ),
    )
    snapshot = collect_dirty_snapshot(tmp_path)
    assert snapshot.git_available is False

    dirty = collect_dirty_paths(tmp_path, scoped_paths=("pkg/a.py",))
    assert dirty.git_available is False

    payload = WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=("pkg/a.py",),
        dirty_paths_in_scope=("pkg/a.py",),
        dirty_paths_outside_scope=(),
        foreign_dirty_overlaps=(),
        blocks_edit=False,
        dirty_attribution=(
            DirtyAttribution(
                path="pkg/a.py",
                scope_relation="own_allowed",
                evidence="present",
                start_state="present_same",
                intent_attribution="none",
                classification="declared_scope_dirty",
                blocking=False,
            ),
        ),
        files_for_scope_check=("pkg/a.py",),
    ).to_payload(detail_level="full")
    assert "dirty_attribution" in payload
    assert "files_for_scope_check" in payload


def test_dirty_snapshot_from_payload_invalid_shapes() -> None:
    assert dirty_snapshot_from_payload("bad") is None
    assert dirty_snapshot_from_payload({"git_available": True}) is None
    assert (
        dirty_snapshot_from_payload(
            {
                "git_available": True,
                "captured_at_utc": "x",
                "entries": {"a.py": {"status_xy": 1, "digest_status": "ok"}},
            }
        )
        is None
    )
    assert (
        dirty_snapshot_from_payload(
            {
                "git_available": True,
                "captured_at_utc": "x",
                "entries": [],
            }
        )
        is None
    )
    assert (
        dirty_snapshot_from_payload(
            {
                "git_available": True,
                "captured_at_utc": "x",
                "entries": {1: {}},
            }
        )
        is None
    )
    assert (
        dirty_snapshot_from_payload(
            {
                "git_available": True,
                "captured_at_utc": "x",
                "entries": {"../a.py": {"status_xy": " M", "digest_status": "ok"}},
            }
        )
        is None
    )
    assert (
        dirty_snapshot_from_payload(
            {
                "git_available": True,
                "captured_at_utc": "x",
                "entries": {
                    "a.py": {"status_xy": " M", "digest": 1, "digest_status": "ok"}
                },
            }
        )
        is None
    )


def test_workspace_hygiene_state_helpers_and_finish_short_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=(),
        dirty_paths_in_scope=(),
        dirty_paths_outside_scope=(),
        foreign_dirty_overlaps=(),
        blocks_edit=False,
        dirty_attribution=(),
        files_for_scope_check=("pkg/a.py",),
    ).to_payload(detail_level="full")
    assert "files_for_scope_check" in payload

    current = DirtySnapshotEntry(
        path="pkg/a.py",
        status_xy=" M",
        digest="a" * 64,
        digest_status="ok",
    )
    start = DirtySnapshotEntry(
        path="pkg/a.py",
        status_xy=" M",
        digest="a" * 64,
        digest_status="unavailable",
    )
    snapshot = DirtySnapshot(git_available=True, captured_at_utc="x", entries=())
    assert _dirty_start_state(None, start, snapshot=snapshot) == "cleaned"
    assert _dirty_start_state(current, start, snapshot=snapshot) == "unknown"

    # Finish derives git availability from the single finish snapshot: when
    # collect_dirty_snapshot reports git unavailable, finish_hygiene_check
    # returns the degraded envelope (there is no second scoped read to consult).
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.collect_dirty_snapshot",
        lambda _root: DirtySnapshot(
            git_available=False, captured_at_utc="x", entries=()
        ),
    )
    result = finish_hygiene_check(
        root=tmp_path,
        allowed_files=("pkg/a.py",),
        allowed_related=(),
        resolved_files=("pkg/a.py",),
        store=get_workspace_intent_store(tmp_path),
        own_pid=1,
        own_start_epoch=1,
        own_intent_id="intent-a",
    )
    assert result.git_available is False
