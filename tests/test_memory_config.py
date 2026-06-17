# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.pyproject_loader import (
    ConfigValidationError,
    load_pyproject_config,
)


def test_load_pyproject_config_accepts_memory_nested_table(tmp_path: Path) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        """
[tool.codeclone.memory]
backend = "sqlite"
db_path = ".codeclone/memory/engineering_memory.sqlite3"
max_records = 5000
trajectories_enabled = true
trajectory_retention_days = 730
""".strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = load_pyproject_config(tmp_path)
    memory = loaded.get("memory")
    assert isinstance(memory, dict)
    assert memory["backend"] == "sqlite"
    assert memory["max_records"] == 5000
    assert memory["trajectories_enabled"] is True
    assert memory["trajectory_retention_days"] == 730


def test_load_pyproject_config_rejects_unknown_memory_key(tmp_path: Path) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        """
[tool.codeclone.memory]
unknown_key = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigValidationError,
        match=r"Unknown key\(s\) in tool\.codeclone\.memory",
    ):
        load_pyproject_config(tmp_path)


def test_ingest_config_validator_passthrough_non_dict() -> None:
    from codeclone.config.memory import IngestConfig

    assert IngestConfig._normalize_path_lists.__func__(IngestConfig, 42) == 42
