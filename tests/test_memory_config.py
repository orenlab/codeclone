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
""".strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = load_pyproject_config(tmp_path)
    memory = loaded.get("memory")
    assert isinstance(memory, dict)
    assert memory["backend"] == "sqlite"
    assert memory["max_records"] == 5000


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
