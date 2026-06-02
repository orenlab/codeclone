# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from codeclone.surfaces.mcp._workspace_hygiene import (
    DirtySnapshot,
    DirtySnapshotEntry,
    _untracked_file_digest,
)


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
