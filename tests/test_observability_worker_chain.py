# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import orjson
import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.config.observability import ObservabilityConfig
from codeclone.memory.jobs import worker as worker_module
from codeclone.memory.jobs.worker import run_projection_job
from codeclone.observability import bootstrap, shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)

from .memory_fixtures import cli_memory_repo


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def test_run_projection_job_emits_operation_and_spans(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        config = resolve_memory_config(root)
        bootstrap(ObservabilityConfig(enabled=True), root=root)
        try:
            with (
                patch.object(
                    worker_module,
                    "execute_trajectory_rebuild",
                    return_value={"status": "ok", "mode": "full", "workflows_seen": 7},
                ) as trajectory_rebuild,
                patch.object(
                    worker_module,
                    "execute_semantic_index_rebuild",
                    return_value={
                        "status": "ok",
                        "embedded": 1423,
                        "skipped_unchanged": 11,
                    },
                ) as semantic_rebuild,
                patch.object(
                    worker_module,
                    "execute_experience_distillation",
                    return_value={"status": "ok", "experiences_distilled": 3},
                ) as experience_distillation,
            ):
                status, _result, _reason = run_projection_job(
                    store,
                    job_id="job-1",
                    root_path=root,
                    config=config,
                    project=project,
                    stimulus={},
                )
        finally:
            shutdown()

        assert status == "done"
        assert trajectory_rebuild.call_args.kwargs["store"] is store
        assert semantic_rebuild.call_args.kwargs["store"] is store
        assert experience_distillation.call_args.kwargs["store"] is store

        obs = open_observability_store(observability_store_path(root))
        try:
            op_rows = obs.execute(
                "SELECT name, surface, status FROM platform_operations"
            ).fetchall()
            span_rows = obs.execute(
                "SELECT name, reason_kind, counters_json, operation_id "
                "FROM platform_spans"
            ).fetchall()
        finally:
            obs.close()

    assert op_rows == [("memory.projection.job", "memory", "ok")]
    by_name = {row[0]: row for row in span_rows}
    assert set(by_name) == {
        "memory.trajectory.rebuild",
        "memory.semantic.reindex",
        "memory.experience.distill",
    }
    # All spans hang off the single job operation.
    assert len({row[3] for row in span_rows}) == 1
    # Empty memory DB has no applied stimulus -> first index, deterministic.
    assert by_name["memory.trajectory.rebuild"][1] == "first_index"
    # Semantic has no deterministic reason_kind signal yet -> unclassified (NULL),
    # which is intentionally NOT counted as an "unknown expensive rebuild".
    assert by_name["memory.semantic.reindex"][1] is None
    assert orjson.loads(by_name["memory.trajectory.rebuild"][2]) == {
        "workflows_seen": 7
    }
    assert orjson.loads(by_name["memory.semantic.reindex"][2]) == {
        "embedded": 1423,
        "skipped_unchanged": 11,
    }
    assert orjson.loads(by_name["memory.experience.distill"][2]) == {
        "experiences_distilled": 3
    }
