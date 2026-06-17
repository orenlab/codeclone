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
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(
        TypeError,
        match="memory\\.db_path must resolve to a string path",
    ):
        resolve_memory_config(
            root,
            pyproject_config={
                "memory": {
                    "db_path": 123,
                }
            },
        )


def test_intent_registry_path_must_stay_under_repo(tmp_path: Path) -> None:
    from codeclone.config.intent_registry import (
        IntentRegistryConfigError,
        resolve_intent_registry_db_path,
    )

    root = tmp_path / "repo"
    root.mkdir()
    outside = (tmp_path / "outside" / "intents.sqlite3").resolve()
    with pytest.raises(IntentRegistryConfigError, match="relative to the repository"):
        resolve_intent_registry_db_path(
            root_path=root,
            value=str(outside),
        )


def test_memory_state_path_validation_errors(tmp_path: Path) -> None:
    from codeclone.config.memory import _resolve_memory_state_path

    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(TypeError, match="must resolve to a string path"):
        _resolve_memory_state_path(
            key="memory.semantic.index_path",
            value=123,
            root_path=root,
        )
    with pytest.raises(ValueError, match="must stay under the repository root"):
        _resolve_memory_state_path(
            key="memory.semantic.index_path",
            value="../outside.lance",
            root_path=root,
        )
