# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Where an MCP execution of a test root publishes its run store, said once.

The MCP surface writes a run store only inside CodeClone's service
directories of the analysed root (its write boundary, the one the analysis
cache obeys): a store a fixture put beside the root would be withheld, and
every pin over it would be measuring an absent run.  So every MCP fixture
publishes into the root's own store, at the product's default path.

Shallow on purpose: one edge, to the product's layout constant.  A test
module that took these from ``tests.conftest`` would hang the whole conftest
import chain under itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.paths.workspace import REL_RUN_STORE_DB_PATH


def run_store_service_path(root: Path) -> Path:
    """The store an MCP execution of ``root`` publishes into: the product's
    default store path, inside the root's own ``.codeclone/``.  Spelled
    through the product's constant, so a moved default moves every MCP
    fixture with it."""
    return root / REL_RUN_STORE_DB_PATH


def name_run_store(monkeypatch: pytest.MonkeyPatch, store_path: Path) -> None:
    """Name ``store_path`` to the rollout the way a user would.

    A store at a root's default path (:func:`run_store_service_path`) is
    named by the default -- the variable unset -- so every root an MCP
    session analyses resolves its OWN store, exactly as a user's server
    does, and a session over two roots reads each run where it was
    published.  Any other path is named by ``CODECLONE_RUN_STORE_PATH``.
    """
    if store_path.parts[-3:] == Path(REL_RUN_STORE_DB_PATH).parts:
        monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
    else:
        monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store_path))


__all__ = ["name_run_store", "run_store_service_path"]
