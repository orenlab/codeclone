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
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", ".codeclone/custom.sqlite3")
    config = resolve_memory_config(root)
    assert config.db_path == (root / ".codeclone" / "custom.sqlite3")


def test_resolve_memory_config_rejects_external_env_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", str(tmp_path / "custom.sqlite3"))
    with pytest.raises(ValueError, match="memory\\.db_path"):
        resolve_memory_config(root)


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


def test_resolve_memory_config_accepts_trajectory_keys(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.codeclone.memory]",
                "trajectories_enabled = false",
                "trajectory_retention_days = 42",
            ]
        ),
        encoding="utf-8",
    )

    config = resolve_memory_config(root)

    assert config.trajectories_enabled is False
    assert config.trajectory_retention_days == 42


def test_resolve_memory_config_rejects_invalid_trajectory_enabled(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.codeclone.memory]\ntrajectories_enabled = "maybe"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trajectories_enabled"):
        resolve_memory_config(root)
