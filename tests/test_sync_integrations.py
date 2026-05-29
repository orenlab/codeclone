# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.sync_integrations import (
    SYNC_TARGETS,
    SyncTarget,
    SyncValidationError,
    main,
    sync_target,
    validate_source,
    validate_target,
)


def _write(path: Path, text: str = "content\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ("git", *args),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "CodeClone Tests")


def _commit_all(path: Path) -> None:
    _git(path, "add", ".")
    _git(path, "commit", "-m", "fixture")


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    _init_git(source)
    _write(
        source / "pyproject.toml",
        '[project]\nname = "codeclone"\nversion = "9.8.7"\n',
    )
    _write(source / "plugins" / "codeclone" / "README.md", "# Codex\n")
    _write(source / "plugins" / "codeclone" / "skills" / "review" / "SKILL.md")
    _write(
        source / "plugins" / "codeclone" / "scripts" / "launch_mcp.py",
        "def resolve_launch_target():\n    return None\n",
    )
    _write(
        source / ".agents" / "plugins" / "marketplace.json",
        '{"plugins":[]}\n',
    )
    _write(
        source / "extensions" / "claude-desktop-codeclone" / "manifest.json",
        "{}\n",
    )
    _write(source / "extensions" / "vscode-codeclone" / "package.json", "{}\n")
    _write(source / "extensions" / "vscode-codeclone" / "src" / "extension.js")
    _write(
        source / "plugins" / "cursor-codeclone" / ".cursor-plugin" / "plugin.json",
        "{}\n",
    )
    _write(source / "plugins" / "cursor-codeclone" / "rules" / "workflow.mdc")
    _write(
        source / "plugins" / "cursor-codeclone" / "scripts" / "launch_mcp.py",
        "import runpy\n",
    )
    _commit_all(source)
    return source


def _make_target(tmp_path: Path, name: str) -> Path:
    target = tmp_path / f"codeclone-{name}"
    _init_git(target)
    return target


def _load_manifest(target: Path) -> dict[str, object]:
    payload = json.loads((target / "SYNC_MANIFEST.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_sync_copies_files_and_writes_manifest(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "codex")

    result = sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["codex"],
        allow_dirty=False,
        dry_run=False,
    )

    assert result.files_copied == 4
    assert result.files_deleted == 0
    assert (target / "plugins" / "codeclone" / "README.md").is_file()
    assert (target / ".agents" / "plugins" / "marketplace.json").is_file()
    manifest = _load_manifest(target)
    assert {
        "source_repository": manifest["source_repository"],
        "source_dirty": manifest["source_dirty"],
        "codeclone_version": manifest["codeclone_version"],
        "target": manifest["target"],
        "files_copied": manifest["files_copied"],
        "files_deleted": manifest["files_deleted"],
    } == {
        "source_repository": "orenlab/codeclone",
        "source_dirty": False,
        "codeclone_version": "9.8.7",
        "target": "codex",
        "files_copied": 4,
        "files_deleted": 0,
    }


def test_sync_deletes_only_allowlisted_paths(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "codex")
    _write(target / "plugins" / "codeclone" / "stale.txt")
    _write(target / ".github" / "workflows" / "ci.yml")
    _write(target / "KEEP.md")
    _write(target / "SYNC_MANIFEST.json", "{}\n")

    result = sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["codex"],
        allow_dirty=False,
        dry_run=False,
    )

    assert result.files_deleted == 2
    assert not (target / "plugins" / "codeclone" / "stale.txt").exists()
    assert (target / ".github" / "workflows" / "ci.yml").is_file()
    assert (target / "KEEP.md").is_file()


def test_sync_respects_global_denylist(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    _write(source / "plugins" / "codeclone" / "__pycache__" / "x.pyc")
    _write(source / "plugins" / "codeclone" / ".DS_Store")
    _write(source / "plugins" / "codeclone" / "node_modules" / "pkg" / "index.js")
    _commit_all(source)
    target = _make_target(tmp_path, "codex")

    sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["codex"],
        allow_dirty=False,
        dry_run=False,
    )

    assert not (target / "plugins" / "codeclone" / "__pycache__").exists()
    assert not (target / "plugins" / "codeclone" / ".DS_Store").exists()
    assert not (target / "plugins" / "codeclone" / "node_modules").exists()


def test_sync_respects_per_target_denylist(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    _write(source / "extensions" / "vscode-codeclone" / "secret" / "token.txt")
    _commit_all(source)
    target = _make_target(tmp_path, "vscode")
    target_def = replace(SYNC_TARGETS["vscode"], denylist=("secret/**",))

    sync_target(
        source_root=source,
        target_root=target,
        target=target_def,
        allow_dirty=False,
        dry_run=False,
    )

    assert (target / "package.json").is_file()
    assert not (target / "secret").exists()


def test_sync_dry_run_does_not_write(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "codex")

    result = sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["codex"],
        allow_dirty=False,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.files_copied == 4
    assert not (target / "plugins").exists()
    assert not (target / "SYNC_MANIFEST.json").exists()


def test_sync_rejects_dirty_source_without_flag(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    _write(source / "dirty.txt")

    with pytest.raises(SyncValidationError, match="source tree is dirty"):
        validate_source(source, allow_dirty=False)


def test_sync_allows_dirty_source_with_flag(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    _write(source / "dirty.txt")

    source_info = validate_source(source, allow_dirty=True)

    assert source_info.dirty is True


def test_sync_rejects_missing_target(tmp_path: Path) -> None:
    with pytest.raises(SyncValidationError, match="does not exist"):
        validate_target(tmp_path / "codeclone-codex", "codex")


def test_sync_rejects_non_git_target(tmp_path: Path) -> None:
    target = tmp_path / "codeclone-codex"
    target.mkdir()

    with pytest.raises(SyncValidationError, match="not a git repo"):
        validate_target(target, "codex")


def test_sync_rejects_path_traversal(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "bad")
    bad_target = SyncTarget(
        name="bad",
        copies=(("plugins/codeclone", "../outside"),),
        generated=("SYNC_MANIFEST.json",),
    )

    with pytest.raises(SyncValidationError, match="path traversal"):
        sync_target(
            source_root=source,
            target_root=target,
            target=bad_target,
            allow_dirty=False,
            dry_run=False,
        )


def test_sync_all_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_source(tmp_path)
    base_dir = tmp_path / "targets"
    for name in SYNC_TARGETS:
        _make_target(base_dir, name)
    monkeypatch.chdir(source)

    exit_code = main(["--all", "--base-dir", str(base_dir)])

    assert exit_code == 0
    for name in SYNC_TARGETS:
        assert (base_dir / f"codeclone-{name}" / "SYNC_MANIFEST.json").is_file()


def test_manifest_fields(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "cursor")

    sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["cursor"],
        allow_dirty=False,
        dry_run=False,
    )

    manifest = _load_manifest(target)
    assert set(manifest) == {
        "codeclone_version",
        "files_copied",
        "files_deleted",
        "source_commit",
        "source_commit_full",
        "source_dirty",
        "source_paths",
        "source_repository",
        "synced_at_utc",
        "target",
    }
    assert isinstance(manifest["source_commit"], str)
    assert isinstance(manifest["source_commit_full"], str)
    assert isinstance(manifest["source_dirty"], bool)
    assert isinstance(manifest["source_paths"], list)
    assert isinstance(manifest["files_copied"], int)
    assert isinstance(manifest["files_deleted"], int)


def test_flat_layout_copies_to_root(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "vscode")

    sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["vscode"],
        allow_dirty=False,
        dry_run=False,
    )

    assert (target / "package.json").is_file()
    assert (target / "src" / "extension.js").is_file()
    assert not (target / "extensions").exists()


def test_nested_layout_preserves_structure(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "codex")

    sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["codex"],
        allow_dirty=False,
        dry_run=False,
    )

    assert (target / "plugins" / "codeclone" / "README.md").is_file()
    assert not (target / "README.md").exists()


def test_sync_source_paths_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    for target in SYNC_TARGETS.values():
        for source_rel, _destination_rel in target.copies:
            source_path = root / source_rel
            assert source_path.exists(), (
                f"missing sync source {source_rel} for target {target.name}"
            )


def test_cursor_sync_ships_standalone_launcher(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    target = _make_target(tmp_path, "cursor")

    sync_target(
        source_root=source,
        target_root=target,
        target=SYNC_TARGETS["cursor"],
        allow_dirty=False,
        dry_run=False,
    )

    launcher = (target / "scripts" / "launch_mcp.py").read_text(encoding="utf-8")
    assert "resolve_launch_target" in launcher
    assert "runpy" not in launcher
