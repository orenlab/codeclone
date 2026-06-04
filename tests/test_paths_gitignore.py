# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.paths.gitignore import (
    gitignore_pattern_covers_codeclone_cache,
    normalize_gitignore_pattern,
    repo_gitignore_covers_codeclone_cache,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (".cache/", True),
        (".cache", True),
        ("/.cache/", True),
        (".cache/**", True),
        (".codeclone/", True),
        (".codeclone", True),
        (".codeclone/**", True),
        (".codeclone/", True),
        (".codeclone", True),
        (".codeclone/**", True),
        ("**/.codeclone/", True),
        ("**/.codeclone/**", True),
        (".cache/*", False),
        ("node_modules/", False),
        ("", False),
        ("# .cache/", False),
        ("!.codeclone/", False),
    ],
)
def test_gitignore_pattern_covers_codeclone_cache(pattern: str, expected: bool) -> None:
    assert gitignore_pattern_covers_codeclone_cache(pattern) is expected


def test_normalize_gitignore_pattern_strips_comments_and_slashes() -> None:
    assert normalize_gitignore_pattern("  /.codeclone/  ") == ".codeclone"
    assert normalize_gitignore_pattern("# ignore cache") == ""
    assert normalize_gitignore_pattern("\\# .codeclone/") == "# .codeclone"


def test_repo_gitignore_covers_codeclone_cache_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    def raise_oserror(self: Path, encoding: str | None = None) -> str:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_text", raise_oserror)
    assert repo_gitignore_covers_codeclone_cache(tmp_path) is False


def test_repo_gitignore_covers_codeclone_cache(tmp_path: Path) -> None:
    assert repo_gitignore_covers_codeclone_cache(tmp_path) is False

    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    assert repo_gitignore_covers_codeclone_cache(tmp_path) is False

    (tmp_path / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    assert repo_gitignore_covers_codeclone_cache(tmp_path) is True

    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    assert repo_gitignore_covers_codeclone_cache(tmp_path) is True


def test_gitignore_codeclone_cache_tip_payload_shape() -> None:
    from codeclone.paths.gitignore import (
        GITIGNORE_CODECLONE_CACHE_TIP_ID,
        gitignore_codeclone_cache_tip_payload,
    )

    payload = gitignore_codeclone_cache_tip_payload()
    assert payload["id"] == GITIGNORE_CODECLONE_CACHE_TIP_ID
    assert payload["category"] == "workspace_hygiene"
    assert payload["suggested_entry"] == ".codeclone/"
