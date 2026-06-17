# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    display_repo_path,
    resolve_repo_relative_path,
    resolve_under_repo_root,
)


def test_resolve_repo_relative_path_keeps_paths_under_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    assert resolve_repo_relative_path(root, "nested/cache.json") == (
        root / "nested" / "cache.json"
    ).resolve(strict=False)
    assert resolve_repo_relative_path(root, "nested/../cache.json") == (
        root / "cache.json"
    ).resolve(strict=False)


@pytest.mark.parametrize("raw", ["", "   "])
def test_resolve_under_repo_root_rejects_empty_paths(
    tmp_path: Path,
    raw: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(RepoPathError, match="must not be empty"):
        resolve_under_repo_root(root, raw, policy=RepoPathPolicy())


def test_resolve_under_repo_root_rejects_absolute_without_opt_in(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(PathOutsideRepoError, match="absolute paths"):
        resolve_under_repo_root(
            root,
            root / "cache.json",
            policy=RepoPathPolicy(),
        )


def test_resolve_under_repo_root_allows_absolute_under_root_with_opt_in(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "cache.json"

    assert resolve_under_repo_root(
        root,
        target,
        policy=RepoPathPolicy(allow_absolute=True),
    ) == target.resolve(strict=False)


def test_resolve_under_repo_root_rejects_absolute_external_by_default(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external-cache.json"

    with pytest.raises(PathOutsideRepoError, match="absolute paths"):
        resolve_under_repo_root(root, external, policy=RepoPathPolicy())

    with pytest.raises(PathOutsideRepoError, match="escapes repository root"):
        resolve_under_repo_root(
            root,
            external,
            policy=RepoPathPolicy(allow_absolute=True),
        )


def test_resolve_under_repo_root_allows_external_only_with_full_opt_in(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external-cache.json"

    assert resolve_under_repo_root(
        root,
        external,
        policy=RepoPathPolicy(allow_absolute=True, allow_external=True),
    ) == external.resolve(strict=False)


@pytest.mark.parametrize("raw", ["../outside.json", "nested/../../outside.json"])
def test_resolve_under_repo_root_rejects_traversal_escapes(
    tmp_path: Path,
    raw: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(PathOutsideRepoError, match="escapes repository root"):
        resolve_under_repo_root(root, raw, policy=RepoPathPolicy())


def test_resolve_under_repo_root_rejects_symlink_escapes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    link = root / "link"
    try:
        link.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(PathOutsideRepoError, match="escapes repository root"):
        resolve_under_repo_root(root, "link/cache.json", policy=RepoPathPolicy())


def test_resolve_under_repo_root_type_policy(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    file_path = root / "state.sqlite3"
    file_path.write_text("", encoding="utf-8")
    dir_path = root / "state"
    dir_path.mkdir()

    assert (
        resolve_under_repo_root(
            root,
            "state.sqlite3",
            policy=RepoPathPolicy(must_exist=True, must_be_file=True),
        )
        == file_path.resolve()
    )
    assert (
        resolve_under_repo_root(
            root,
            "state",
            policy=RepoPathPolicy(must_exist=True, must_be_dir=True),
        )
        == dir_path.resolve()
    )

    with pytest.raises(RepoPathError, match="must be a file"):
        resolve_under_repo_root(
            root,
            "state",
            policy=RepoPathPolicy(must_exist=True, must_be_file=True),
        )
    with pytest.raises(RepoPathError, match="must be a directory"):
        resolve_under_repo_root(
            root,
            "state.sqlite3",
            policy=RepoPathPolicy(must_exist=True, must_be_dir=True),
        )


def test_resolve_under_repo_root_rejects_missing_when_required(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(RepoPathError, match="cannot resolve path"):
        resolve_under_repo_root(
            root,
            "missing.json",
            policy=RepoPathPolicy(must_exist=True),
        )


def test_display_repo_path_uses_relative_path_when_possible(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert display_repo_path(root, root / "nested" / "x.py") == "nested/x.py"
    assert display_repo_path(root, tmp_path / "outside.py") == str(
        tmp_path / "outside.py"
    )


def test_resolve_under_repo_root_requires_directory_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(RepoPathError, match="cannot resolve repository root"):
        resolve_under_repo_root(missing, "x", policy=RepoPathPolicy())

    file_root = tmp_path / "repo.py"
    file_root.write_text("", encoding="utf-8")
    with pytest.raises(RepoPathError, match="not a directory"):
        resolve_under_repo_root(file_root, "x", policy=RepoPathPolicy())
