# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.paths import (
    MEMORY_ROOT_SCOPE_ERROR,
    expand_scope_paths,
    is_root_scope_path,
    normalize_memory_scope_path,
    normalize_repo_path,
    repo_path_to_module_key,
    subject_matches_scope,
)


def test_repo_path_to_module_key_strips_py_suffix() -> None:
    assert (
        repo_path_to_module_key("codeclone/memory/sqlite_store.py")
        == "codeclone.memory.sqlite_store"
    )


def test_repo_path_to_module_key_trims_init_module() -> None:
    assert repo_path_to_module_key("codeclone/memory/__init__.py") == "codeclone.memory"


def test_normalize_repo_path_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="traversal"):
        normalize_repo_path("../secret.py")


@pytest.mark.parametrize("raw_path", [".", "", "./"])
def test_is_root_scope_path_detects_project_root_markers(raw_path: str) -> None:
    normalized = normalize_repo_path(raw_path)
    assert is_root_scope_path(normalized)


def test_normalize_memory_scope_path_rejects_project_root() -> None:
    with pytest.raises(MemoryContractError, match=MEMORY_ROOT_SCOPE_ERROR):
        normalize_memory_scope_path(".")


def test_expand_scope_paths_includes_module_key() -> None:
    expanded = expand_scope_paths(
        frozenset({"codeclone/memory/ingest/mcp_sync.py"}),
    )
    assert "codeclone/memory/ingest/mcp_sync.py" in expanded
    assert "codeclone.memory.ingest.mcp_sync" in expanded


def test_subject_matches_scope_accepts_module_subject_for_path_scope() -> None:
    scope = expand_scope_paths(
        frozenset({"codeclone/memory/ingest/mcp_sync.py"}),
    )
    assert (
        subject_matches_scope("codeclone.memory.ingest.mcp_sync", scope_paths=scope)
        == 1.0
    )
