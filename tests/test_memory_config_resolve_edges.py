# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config


def test_resolve_memory_config_rejects_bool_for_int_fields(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="expected integer"):
        resolve_memory_config(
            root,
            pyproject_config={
                "memory": {
                    "active_retention_days": True,
                }
            },
        )


def test_resolve_memory_config_rejects_non_digit_int_string(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="expected integer"):
        resolve_memory_config(
            root,
            pyproject_config={
                "memory": {
                    "max_records": "12a3",
                }
            },
        )


def test_resolve_memory_config_rejects_non_string_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    # Force the normalizer to return non-str to cover the TypeError branch.
    monkeypatch.setattr(
        "codeclone.config.memory.normalize_path_config_value",
        lambda **_kwargs: 123,
    )

    with pytest.raises(
        TypeError,
        match="memory db_path must resolve to a string path",
    ):
        resolve_memory_config(
            root,
            pyproject_config={
                "memory": {
                    "db_path": ".cache/codeclone/memory.sqlite3",
                }
            },
        )
