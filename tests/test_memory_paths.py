# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.memory.paths import normalize_repo_path, repo_path_to_module_key


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
