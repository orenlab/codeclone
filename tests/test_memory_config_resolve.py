# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config


def test_resolve_memory_config_env_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    custom = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", str(custom))
    config = resolve_memory_config(root)
    assert config.db_path == custom.resolve()


def test_resolve_memory_config_rejects_invalid_backend(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.codeclone.memory]\nbackend = "postgres"\n',
        encoding="utf-8",
    )
    config = resolve_memory_config(root)
    assert config.backend == "postgres"


@pytest.mark.parametrize(
    "pyproject_fragment",
    [
        '[tool.codeclone.memory]\nmax_records = "nope"\n',
        "[tool.codeclone.memory]\nmax_records = true\n",
    ],
)
def test_resolve_memory_config_rejects_invalid_max_records(
    tmp_path: Path,
    pyproject_fragment: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(pyproject_fragment, encoding="utf-8")
    with pytest.raises(ValueError, match="max_records"):
        resolve_memory_config(root)
