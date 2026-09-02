# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeclone.contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION
from codeclone.observability.models import (
    OperationRecord,
    ProfileSample,
    SpanRecord,
)
from codeclone.observability.query import query_platform_observability
from codeclone.observability.store.reader import (
    build_trace_view,
    open_observability_store_readonly,
)
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation
from codeclone.observability.views import DbFingerprintRow, TraceView


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
                        name="memory.semantic.rebuild",
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


def _read_trace(tmp_path: Path, *, correlation_id: str) -> TraceView:
    read = open_observability_store_readonly(tmp_path)
    assert read is not None
    try:
        return build_trace_view(read, correlation_id=correlation_id)
    finally:
        read.close()


def test_open_readonly_missing_store_returns_none(tmp_path: Path) -> None:
    assert open_observability_store_readonly(tmp_path) is None


def test_build_trace_view_tree_and_aggregates(tmp_path: Path) -> None:
    _seed(tmp_path)
    trace = _read_trace(tmp_path, correlation_id="A")

    assert trace.schema_version == PLATFORM_OBSERVABILITY_SCHEMA_VERSION
    assert len(trace.operation_tree) == 1
    root = trace.operation_tree[0]
    assert root.operation_id == "A"
    assert len(root.children) == 1
    child = root.children[0]
    assert child.operation_id == "B"
    assert {span.name for span in child.spans} == {
        "memory.semantic.rebuild",
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

    assert agg.slowest_span is not None
    assert agg.slowest_span.name == "memory.semantic.rebuild"
    assert agg.slowest_span.operation_name == "memory.projection.job"
    assert agg.slowest_span.produced == 1423
    assert agg.slowest_span.no_op is False
    assert [s.name for s in agg.semantic_costs] == [
        "memory.semantic.rebuild",
        "memory.trajectory.rebuild",
    ]

    # Waterfall: one timeline for the A->B chain; B starts 1s after the root A,
    # spans nest a level deeper, offsets are relative to the group start.
    assert len(trace.waterfall) == 1
    group = trace.waterfall[0]
    assert group.correlation_id == "A"
    rows = {(row.label, row.kind): row for row in group.rows}
    assert rows[("finish_controlled_change", "operation")].depth == 0
    assert rows[("finish_controlled_change", "operation")].offset_ms == 0.0
    job_row = rows[("memory.projection.job", "operation")]
    assert job_row.depth == 1
    assert job_row.offset_ms == 1000.0
    assert rows[("memory.semantic.rebuild", "span")].depth == 2

    # Top memory consumer: the reindex span carries the largest rss delta.
    assert agg.peak_memory_span is not None
    assert agg.peak_memory_span.name == "memory.semantic.rebuild"
    assert agg.peak_memory_span.rss_delta_mb == 6144.0


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


def test_no_op_span_and_mcp_payload_percentiles(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="M",
                correlation_id="M",
                surface="mcp",
                name="finish_controlled_change",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=120.0,
                status="ok",
                request_bytes=51,
                response_bytes=1873,
                request_tokens=13,
                response_tokens=469,
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="W",
                correlation_id="M",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:02Z",
                duration_ms=900.0,
                status="ok",
                parent_operation_id="M",
                spans=(
                    SpanRecord(
                        span_id="sx",
                        operation_id="W",
                        name="memory.semantic.rebuild",
                        started_at_utc="2026-06-09T00:00:02Z",
                        duration_ms=850.0,
                        status="ok",
                        reason_kind="content_changed",
                        counters={"embedded": 0, "skipped_unchanged": 1423},
                    ),
                ),
            ),
        )
    finally:
        conn.close()

    trace = _read_trace(tmp_path, correlation_id="M")

    tool = trace.aggregates.mcp_tools[0]
    assert tool.p95_request_bytes == 51
    assert tool.p95_response_bytes == 1873
    assert tool.p95_response_tokens == 469

    costly = trace.aggregates.semantic_costs[0]
    assert costly.name == "memory.semantic.rebuild"
    # embedded present and zero -> the reindex ran but produced nothing.
    assert costly.no_op is True
    assert costly.produced == 0
    assert costly.skipped == 1423

    # Agent context: the one MCP op contributes its response context units.
    agent = trace.aggregates.agent
    assert agent is not None
    assert agent.mcp_calls == 1
    assert agent.response_tokens == 469
    assert agent.consumers[0].name == "finish_controlled_change"
    assert agent.consumers[0].response_tokens == 469


def test_cli_semantic_rebuild_span_in_pipeline_costs(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="C",
                correlation_id="C",
                surface="cli",
                name="cli.memory.semantic.rebuild",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=1380.0,
                status="ok",
                spans=(
                    SpanRecord(
                        span_id="sr",
                        operation_id="C",
                        name="memory.semantic.rebuild",
                        started_at_utc="2026-06-09T00:00:01Z",
                        duration_ms=1380.0,
                        status="ok",
                        reason_kind="manual_rebuild",
                        counters={
                            "embedded": 0,
                            "skipped_unchanged": 1502,
                            "indexed": 1502,
                        },
                    ),
                ),
            ),
        )
    finally:
        conn.close()

    trace = _read_trace(tmp_path, correlation_id="C")
    costs = trace.aggregates.semantic_costs
    assert len(costs) == 1
    assert costs[0].name == "memory.semantic.rebuild"
    assert costs[0].surface == "cli"
    assert costs[0].no_op is True
    assert costs[0].reason_kind == "manual_rebuild"
    assert costs[0].skipped == 1502


def test_db_costs_aggregate_per_span(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="W",
                correlation_id="W",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=900.0,
                status="ok",
                spans=(
                    SpanRecord(
                        span_id="s1",
                        operation_id="W",
                        name="memory.semantic.rebuild",
                        started_at_utc="2026-06-09T00:00:01Z",
                        duration_ms=800.0,
                        status="ok",
                        counters={"db_queries": 1306, "embedded": 9},
                    ),
                    SpanRecord(
                        span_id="s2",
                        operation_id="W",
                        name="memory.experience.distill",
                        started_at_utc="2026-06-09T00:00:02Z",
                        duration_ms=20.0,
                        status="ok",
                        counters={"db_queries": 1875, "db_writes": 768},
                    ),
                ),
            ),
        )
    finally:
        conn.close()

    trace = _read_trace(tmp_path, correlation_id="W")

    costs = trace.aggregates.db_costs
    # Sorted by total queries desc: distill (1875) before reindex (1306).
    assert costs[0].span_name == "memory.experience.distill"
    assert costs[0].total_queries == 1875
    assert costs[0].total_writes == 768
    by_name = {row.span_name: row for row in costs}
    assert by_name["memory.semantic.rebuild"].total_queries == 1306
    assert by_name["memory.semantic.rebuild"].total_writes == 0
    assert by_name["memory.semantic.rebuild"].max_queries == 1306


def test_db_fingerprints_aggregate_per_shape(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="F",
                correlation_id="F",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=500.0,
                status="ok",
                spans=(
                    SpanRecord(
                        span_id="f1",
                        operation_id="F",
                        name="memory.experience.distill",
                        started_at_utc="2026-06-09T00:00:01Z",
                        duration_ms=400.0,
                        status="ok",
                        db_fingerprints={
                            "select * from memory_evidence where memory_id = ?": 1200,
                            "select * from memory_subjects where id = ?": 500,
                        },
                    ),
                ),
            ),
        )
    finally:
        conn.close()

    shapes = _read_trace(tmp_path, correlation_id="F").aggregates.db_fingerprints

    # Ranked by count desc; table_hint is re-derived from the stored shape. Assert
    # the whole row at once (a flat run of per-field asserts clones other tests).
    assert shapes[0] == DbFingerprintRow(
        span_name="memory.experience.distill",
        surface="memory",
        fingerprint="select * from memory_evidence where memory_id = ?",
        table_hint="memory_evidence",
        count=1200,
        kind="select",
        summary="by memory_id",
    )
    assert shapes[1].table_hint == "memory_subjects"


def test_waste_ranks_no_op_and_high_payload(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="M",
                correlation_id="M",
                surface="mcp",
                name="get_relevant_memory",
                started_at_utc="2026-06-09T00:00:00Z",
                duration_ms=200.0,
                status="ok",
                response_bytes=20480,
                response_tokens=11000,
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="W",
                correlation_id="M",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=850.0,
                status="ok",
                parent_operation_id="M",
                spans=(
                    SpanRecord(
                        span_id="s",
                        operation_id="W",
                        name="memory.semantic.rebuild",
                        started_at_utc="2026-06-09T00:00:01Z",
                        duration_ms=800.0,
                        status="ok",
                        counters={"embedded": 0, "skipped_unchanged": 826},
                    ),
                ),
            ),
        )
    finally:
        conn.close()

    trace = _read_trace(tmp_path, correlation_id="M")

    waste = trace.aggregates.waste
    assert {w.kind for w in waste} == {"no-op", "high payload"}
    noop = next(w for w in waste if w.kind == "no-op")
    assert noop.subject == "memory.semantic.rebuild"
    assert "skipped 826" in noop.detail
    high = next(w for w in waste if w.kind == "high payload")
    assert high.subject == "get_relevant_memory"
    # High payload (20 KB) outranks the no-op span (800 ms) by severity.
    assert waste[0].kind == "high payload"


def test_cpu_and_pipeline_rollup(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="W",
                correlation_id="W",
                surface="memory",
                name="memory.projection.job",
                started_at_utc="2026-06-09T00:00:00Z",
                duration_ms=1000.0,
                status="ok",
                profile=ProfileSample(cpu_user_ms=1800.0, cpu_system_ms=200.0),
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="A",
                correlation_id="W",
                surface="mcp",
                name="mcp.analyze_repository",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=500.0,
                status="ok",
                parent_operation_id="W",
                profile=ProfileSample(cpu_user_ms=100.0, cpu_system_ms=50.0),
            ),
        )
    finally:
        conn.close()

    agg = _read_trace(tmp_path, correlation_id="W").aggregates
    # Heaviest CPU: the memory job spent 2000ms CPU on 1000ms wall (parallel).
    assert agg.heaviest_cpu is not None
    assert agg.heaviest_cpu.name == "memory.projection.job"
    assert agg.heaviest_cpu.cpu_user_ms == 1800.0
    # Pipeline rolls ops up by subsystem.
    pipe = {group.name: group for group in agg.pipeline}
    assert pipe["memory"].cpu_ms == 2000.0
    assert pipe["analysis"].op_count == 1


def test_epoch_ms_and_empty_correlation_filter(tmp_path: Path) -> None:
    from codeclone.observability.store.reader import _by_correlations, _epoch_ms
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )

    assert _epoch_ms("") == 0.0
    assert _epoch_ms("not-a-date") == 0.0
    assert _epoch_ms("2026-01-01T00:00:00Z") > 0.0

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        assert _by_correlations(conn, []) == []
    finally:
        conn.close()


def test_build_trace_view_on_empty_store_returns_empty_window(tmp_path: Path) -> None:
    open_observability_store(observability_store_path(tmp_path)).close()
    read = open_observability_store_readonly(tmp_path)
    assert read is not None
    try:
        trace = build_trace_view(read)
    finally:
        read.close()
    assert trace.aggregates.operation_count == 0
    assert trace.operation_tree == ()


def test_reader_counter_and_optional_float_helpers() -> None:
    import sqlite3

    from codeclone.observability.store.reader import _optional_float, _parse_counters

    assert _parse_counters(None) == {}
    assert _parse_counters(b"[]") == {}
    assert _parse_counters(b'{"hits": 3, "bad": true, "ok": "4"}') == {
        "hits": 3,
        "ok": 4,
    }

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT NULL AS value").fetchone()
        assert row is not None
        assert _optional_float(row, "missing") is None
        assert _optional_float(row, "value") is None
        numeric = conn.execute("SELECT 1.5 AS value").fetchone()
        assert numeric is not None
        assert _optional_float(numeric, "value") == 1.5
    finally:
        conn.close()


_PRE_RETENTION_STORE_SQL = """
CREATE TABLE platform_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO platform_meta(key, value) VALUES('schema_version', '1.1');
CREATE TABLE platform_operations (
    operation_id TEXT PRIMARY KEY,
    parent_operation_id TEXT,
    correlation_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    plane TEXT,
    error_kind TEXT,
    session_id TEXT,
    repo_root_digest TEXT,
    request_bytes INTEGER,
    response_bytes INTEGER,
    request_tokens INTEGER,
    response_tokens INTEGER,
    rss_mb REAL,
    rss_delta_mb REAL,
    peak_rss_mb REAL,
    peak_rss_delta_mb REAL,
    cpu_user_ms REAL,
    cpu_system_ms REAL,
    open_fds INTEGER,
    thread_count INTEGER
);
CREATE TABLE platform_spans (
    span_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    reason_kind TEXT,
    reason TEXT,
    dedupe_key TEXT,
    counters_json TEXT,
    db_fingerprints TEXT,
    rss_mb REAL,
    rss_delta_mb REAL,
    peak_rss_mb REAL,
    peak_rss_delta_mb REAL,
    cpu_user_ms REAL,
    cpu_system_ms REAL,
    open_fds INTEGER,
    thread_count INTEGER
);
INSERT INTO platform_operations(
    operation_id, correlation_id, surface, name, started_at_utc,
    duration_ms, status, plane
) VALUES('legacy', 'legacy', 'cli', 'cli.analyze',
         '2026-01-01T00:00:00.000000Z', 5.0, 'ok', 'runtime');
INSERT INTO platform_spans(
    span_id, operation_id, name, started_at_utc, duration_ms, status
) VALUES('legacy-span', 'legacy', 'pipeline.discover',
         '2026-01-01T00:00:00.000000Z', 1.0, 'ok');
"""


def _seed_pre_retention_store(root: Path) -> None:
    """A store written before the operation carried its truncation fact.

    Built by hand rather than by migration: open_observability_store would add
    the columns back, and the point is the shape that has neither.
    """
    path = observability_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_PRE_RETENTION_STORE_SQL)
        conn.commit()
    finally:
        conn.close()


def test_store_written_before_span_retention_reads_as_unknown(tmp_path: Path) -> None:
    """The tolerance path is reachable, and it says unknown -- not "none".

    A row with no truncation columns cannot tell whether its spans were cut.
    Reporting zero there would be the same silence this accounting replaced,
    just relocated to the reader.
    """
    _seed_pre_retention_store(tmp_path)

    conn = open_observability_store_readonly(tmp_path)
    assert conn is not None
    try:
        trace = build_trace_view(conn)
    finally:
        conn.close()

    assert trace.span_retention_unknown_operations == 1
    assert trace.span_retention_truncated is False
    assert trace.span_retention_truncated_operations == 0
    assert trace.span_retention_rule is None
    assert trace.span_retention_cap is None
    assert trace.spans_dropped == 0
    assert trace.operation_tree[0].spans_dropped is None
    assert trace.operation_tree[0].span_retention_rule is None


def test_query_warns_that_a_pre_retention_store_cannot_say(tmp_path: Path) -> None:
    _seed_pre_retention_store(tmp_path)

    response = query_platform_observability(root=tmp_path, section="summary")

    retention = response["span_retention"]
    assert isinstance(retention, dict)
    assert retention["operations_unknown"] == 1
    assert retention["truncated"] is False
    warnings = response["warnings"]
    assert isinstance(warnings, list)
    assert any("unknown, not none" in str(text) for text in warnings)
