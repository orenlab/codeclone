# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.paths.workspace import (
    default_cache_path,
    emit_legacy_workspace_warnings,
    legacy_home_cache_path,
    legacy_repo_workspace_dir,
    legacy_repo_workspace_has_artifacts,
    repo_workspace_dir,
    workspace_glob_patterns,
)
from codeclone.surfaces.cli.console import PlainConsole


def test_default_cache_path_under_codeclone_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert default_cache_path(root) == root / ".codeclone" / "cache.json"


def test_legacy_repo_workspace_has_artifacts_detects_entries(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "cache.json").write_text("{}", encoding="utf-8")
    assert legacy_repo_workspace_has_artifacts(root) is True


def test_legacy_repo_workspace_has_artifacts_false_when_missing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert legacy_repo_workspace_has_artifacts(root) is False


def test_repo_workspace_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert repo_workspace_dir(root) == root / ".codeclone"


def test_legacy_repo_workspace_has_artifacts_treats_iterdir_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "marker").write_text("x", encoding="utf-8")
    real_iterdir = Path.iterdir

    def _iterdir(self: Path) -> object:
        if self == legacy:
            raise OSError("permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _iterdir)
    assert legacy_repo_workspace_has_artifacts(root) is False


def test_workspace_glob_patterns_includes_legacy_and_new_globs() -> None:
    patterns = workspace_glob_patterns()
    assert ".codeclone/**" in patterns
    assert ".cache/codeclone/**" in patterns


def test_legacy_home_cache_path_expands_user() -> None:
    path = legacy_home_cache_path()
    assert path.name == "cache.json"
    assert "codeclone" in path.as_posix()


def test_emit_legacy_home_cache_warning_when_paths_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    legacy_home = tmp_path / "legacy-home-cache.json"
    legacy_home.write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=default_cache_path(root),
        legacy_home_cache_path=legacy_home,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out
    assert str(legacy_home) in out


def test_emit_legacy_home_cache_skipped_when_resolved_matches_project_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cache_path = default_cache_path(root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=cache_path,
        legacy_home_cache_path=cache_path,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" not in out


def test_emit_legacy_home_cache_resolve_oserror_still_warns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cache_path = default_cache_path(root)
    legacy_home = tmp_path / "legacy-cache.json"
    legacy_home.write_text("{}", encoding="utf-8")
    real_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        if self == legacy_home:
            raise OSError("nope")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=cache_path,
        legacy_home_cache_path=legacy_home,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out


def test_emit_legacy_repo_workspace_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "cache.json").write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=default_cache_path(root),
        legacy_home_cache_path=tmp_path / "missing-home-cache.json",
        console=PlainConsole(),
    )
    captured = capsys.readouterr()
    out = captured.out
    assert ".cache/codeclone/" in out
    assert str(legacy) in out
    assert str(repo_workspace_dir(root)) in out
