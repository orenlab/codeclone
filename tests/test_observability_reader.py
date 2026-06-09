# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION
from codeclone.observability.models import (
    OperationRecord,
    ProfileSample,
    SpanRecord,
)
from codeclone.observability.store.reader import (
    build_trace_view,
    open_observability_store_readonly,
)
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation


def _seed(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="A",
                correlation_id="A",
                surface="mcp",
                name="finish_controlled_change",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=820.0,
                status="ok",
                response_bytes=900,
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="B",
                correlation_id="A",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:02Z",
                duration_ms=19800.0,
                status="ok",
                parent_operation_id="A",
                spans=(
                    SpanRecord(
                        span_id="s1",
                        operation_id="B",
                        name="memory.semantic.reindex",
                        started_at_utc="2026-06-09T00:00:02Z",
                        duration_ms=18200.0,
                        status="ok",
                        reason_kind="schema_version_changed",
                        counters={"embedded": 1423},
                        profile=ProfileSample(rss_delta_mb=6144.0),
                    ),
                    SpanRecord(
                        span_id="s2",
                        operation_id="B",
                        name="memory.trajectory.rebuild",
                        started_at_utc="2026-06-09T00:00:03Z",
                        duration_ms=1100.0,
                        status="ok",
                        reason_kind="unknown",
                    ),
                ),
            ),
        )
    finally:
        conn.close()


def test_open_readonly_missing_store_returns_none(tmp_path: Path) -> None:
    assert open_observability_store_readonly(tmp_path) is None


def test_build_trace_view_tree_and_aggregates(tmp_path: Path) -> None:
    _seed(tmp_path)
    read = open_observability_store_readonly(tmp_path)
    assert read is not None
    try:
        trace = build_trace_view(read, correlation_id="A")
    finally:
        read.close()

    assert trace.schema_version == PLATFORM_OBSERVABILITY_SCHEMA_VERSION
    assert len(trace.operation_tree) == 1
    root = trace.operation_tree[0]
    assert root.operation_id == "A"
    assert len(root.children) == 1
    child = root.children[0]
    assert child.operation_id == "B"
    assert {span.name for span in child.spans} == {
        "memory.semantic.reindex",
        "memory.trajectory.rebuild",
    }

    agg = trace.aggregates
    assert agg.operation_count == 2
    assert agg.max_rss_delta_mb == 6144.0
    assert agg.unknown_expensive_rebuild_count == 1
    assert agg.slowest[0].operation_id == "B"
    assert agg.largest_responses[0].operation_id == "A"
    assert len(agg.mcp_tools) == 1
    assert agg.mcp_tools[0].name == "finish_controlled_change"
    assert agg.mcp_tools[0].p95_response_bytes == 900


def test_build_trace_view_focus_by_operation_id(tmp_path: Path) -> None:
    _seed(tmp_path)
    read = open_observability_store_readonly(tmp_path)
    assert read is not None
    try:
        trace = build_trace_view(read, operation_id="B")
    finally:
        read.close()
    assert trace.focus_operation is not None
    assert trace.focus_operation.operation_id == "B"
