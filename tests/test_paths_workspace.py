# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.paths.workspace import (
    default_cache_path,
    legacy_repo_workspace_dir,
    legacy_repo_workspace_has_artifacts,
    repo_workspace_dir,
)


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
