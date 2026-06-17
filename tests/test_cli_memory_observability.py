# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.config.observability import ObservabilityConfig
from codeclone.memory.semantic.rebuild_workflow import execute_semantic_index_rebuild
from codeclone.observability import shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import cli_memory_repo


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def test_memory_cli_semantic_rebuild_records_cli_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_ENABLED", "1")
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        with patch(
            "codeclone.surfaces.cli.memory.execute_semantic_index_rebuild",
            return_value={
                "action": "rebuild_semantic_index",
                "status": "ok",
                "index_path": ".codeclone/db/semantic",
                "embedding_provider": "diagnostic",
                "indexed": 3,
                "deleted": 0,
                "embedded": 1,
                "skipped_unchanged": 2,
                "by_source": {"memory": 3},
                "embedding_model": "diagnostic-hash-v1",
            },
        ):
            code = memory_main(["semantic", "rebuild", "--root", str(root)])
        assert code == 0

        obs = open_observability_store(observability_store_path(root))
        try:
            op_row = obs.execute(
                "SELECT name, surface, status FROM platform_operations"
            ).fetchone()
        finally:
            obs.close()
    assert op_row == ("cli.memory.semantic.rebuild", "cli", "ok")


def test_execute_semantic_rebuild_emits_product_spans(tmp_path: Path) -> None:
    from codeclone.observability import bootstrap, operation

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        bootstrap(ObservabilityConfig(enabled=True), root=root)
        try:
            with operation(name="test.semantic.rebuild", surface="memory"):
                payload = execute_semantic_index_rebuild(
                    root_path=root,
                    config=resolve_memory_config(root),
                    store=store,
                    project=project,
                )
        finally:
            shutdown()
        assert payload["status"] == "skipped"
        assert payload["reason"] == "disabled"

        obs = open_observability_store(observability_store_path(root))
        try:
            span_rows = obs.execute(
                "SELECT name, reason_kind, counters_json FROM platform_spans"
            ).fetchall()
        finally:
            obs.close()

    by_name = {row[0]: row for row in span_rows}
    assert "memory.semantic.rebuild" in by_name
