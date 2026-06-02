# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from codeclone.surfaces.mcp._workspace_hygiene import (
    DirtyAttribution,
    DirtySnapshot,
    DirtySnapshotEntry,
    WorkspaceHygieneResult,
    _dirty_entries_from_porcelain,
    _dirty_entry_digest,
    _dirty_start_state,
    _git_diff_bytes,
    _scope_relation,
    _snapshot_status,
    _untracked_file_digest,
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

    digest, status = _untracked_file_digest(root, "pkg/mod.py")
    assert status == "ok"
    assert digest is not None
    assert len(digest) == 64

    outside, outside_status = _untracked_file_digest(root, "../escape.py")
    assert outside is None
    assert outside_status == "unavailable"


def test_git_diff_bytes_returns_none_on_failure(tmp_path: Path) -> None:
    from codeclone.surfaces.mcp import _workspace_hygiene as hygiene_mod

    with patch(
        "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run",
        side_effect=OSError("git missing"),
    ):
        result = hygiene_mod._git_diff_bytes(tmp_path, ["diff", "--", "a.py"])
    assert result is None


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


def test_dirty_entries_from_porcelain_handles_rename_and_blank_rows() -> None:
    output = "\n".join(
        [
            "?? pkg/new.py",
            "R  pkg/old.py -> pkg/newer.py",
            " M   ",
            "x",
        ]
    )
    entries = _dirty_entries_from_porcelain(output)
    assert ("pkg/new.py", "??") in entries
    assert ("pkg/old.py", "R ") in entries
    assert ("pkg/newer.py", "R ") in entries


def test_dirty_entry_digest_and_git_diff_bytes_edge_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene._git_diff_bytes",
        lambda _root, args: b"cached" if "--cached" in args else None,
    )
    digest, status = _dirty_entry_digest(tmp_path, "pkg/a.py", " M")
    assert digest is None
    assert status == "unavailable"

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="text-diff"),
    )
    assert _git_diff_bytes(tmp_path, ["diff", "--", "a.py"]) == b"text-diff"

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=object()),
    )
    assert _git_diff_bytes(tmp_path, ["diff", "--", "a.py"]) is None


def test_untracked_digest_handles_missing_and_open_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    missing_digest, missing_status = _untracked_file_digest(root, "pkg")
    assert missing_digest is None
    assert missing_status == "unavailable"

    target = root / "pkg" / "broken.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    def _boom_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("read failed")

    monkeypatch.setattr(Path, "open", _boom_open)
    digest, status = _untracked_file_digest(root, "pkg/broken.py")
    assert digest is None
    assert status == "unavailable"


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
        "codeclone.surfaces.mcp._workspace_hygiene._git_available",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("git failed")),
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

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene._untracked_file_digest",
        lambda _root, _path: ("u", "ok"),
    )
    assert _dirty_entry_digest(tmp_path, "pkg/new.py", "??") == ("u", "ok")

    class _Completed:
        stdout = b"bin"

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    assert _git_diff_bytes(tmp_path, ["diff"]) == b"bin"

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_hygiene.evaluate_scoped_hygiene",
        lambda **kwargs: WorkspaceHygieneResult(
            git_available=True,
            dirty_paths=("pkg/a.py",),
            dirty_paths_in_scope=("pkg/a.py",),
            dirty_paths_outside_scope=(),
            foreign_dirty_overlaps=(),
            blocks_edit=False,
        ),
    )
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
    assert result.git_available is True
