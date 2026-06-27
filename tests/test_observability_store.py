# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION
from codeclone.observability.models import (
    OperationRecord,
    ProfileSample,
    SpanRecord,
)
from codeclone.observability.store.reader import build_trace_view
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation


def _op(
    operation_id: str,
    *,
    correlation_id: str,
    parent_operation_id: str | None = None,
    spans: tuple[SpanRecord, ...] = (),
) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        correlation_id=correlation_id,
        surface="mcp",
        name="finish_controlled_change",
        started_at_utc="2026-06-09T00:00:00Z",
        duration_ms=820.0,
        status="ok",
        parent_operation_id=parent_operation_id,
        spans=spans,
    )


def _span(span_id: str, **kw: object) -> SpanRecord:
    base: dict[str, object] = {
        "span_id": span_id,
        "operation_id": "A",
        "name": "span",
        "started_at_utc": "2026-06-09T00:00:00Z",
        "duration_ms": 1.0,
        "status": "ok",
    }
    base.update(kw)
    return SpanRecord(**base)  # type: ignore[arg-type]


def test_store_records_schema_version(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT value FROM platform_meta WHERE key='schema_version'"
        ).fetchone()
        assert row[0] == PLATFORM_OBSERVABILITY_SCHEMA_VERSION
    finally:
        conn.close()


def test_write_operation_persists_op_and_spans(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        spans = tuple(
            _span(
                f"s{i}",
                name=f"span{i}",
                duration_ms=float(i),
                reason_kind="content_changed",
                counters={"embedded": i},
            )
            for i in range(5)
        )
        write_operation(conn, _op("A", correlation_id="A", spans=spans))

        assert (
            conn.execute("SELECT COUNT(*) FROM platform_operations").fetchone()[0] == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM platform_spans WHERE operation_id='A'"
            ).fetchone()[0]
            == 5
        )
        reason_kind, counters_json = conn.execute(
            "SELECT reason_kind, counters_json FROM platform_spans WHERE span_id='s3'"
        ).fetchone()
        assert reason_kind == "content_changed"
        assert '"embedded"' in counters_json
    finally:
        conn.close()


def test_write_operation_records_tree_columns(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(conn, _op("A", correlation_id="A"))
        write_operation(conn, _op("B", correlation_id="A", parent_operation_id="A"))
        row = conn.execute(
            "SELECT parent_operation_id, correlation_id "
            "FROM platform_operations WHERE operation_id='B'"
        ).fetchone()
        assert row == ("A", "A")
    finally:
        conn.close()


def test_profile_columns_persist(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        span = _span(
            "p",
            name="memory.semantic.rebuild",
            duration_ms=18200.0,
            profile=ProfileSample(rss_delta_mb=6144.0),
        )
        write_operation(conn, _op("A", correlation_id="A", spans=(span,)))
        rss = conn.execute(
            "SELECT rss_delta_mb FROM platform_spans WHERE span_id='p'"
        ).fetchone()[0]
        assert rss == 6144.0
    finally:
        conn.close()


def test_observability_span_error_and_sql_classification(tmp_path: Path) -> None:
    from codeclone.config.observability import ObservabilityConfig
    from codeclone.observability import (
        bootstrap,
        operation,
        record_elapsed_span,
        shutdown,
        span,
    )
    from codeclone.observability.runtime import _classify_sql
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )

    assert _classify_sql("   ") == ""

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with operation(name="job", surface="cli"):
        record_elapsed_span(
            "cold-start",
            started_at_utc="2026-01-01T00:00:00Z",
            duration_ms=12.5,
        )
        with pytest.raises(RuntimeError, match="boom"), span(name="failing-stage"):
            raise RuntimeError("boom")
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        span_row = conn.execute(
            "SELECT status FROM platform_spans WHERE name=?",
            ("failing-stage",),
        ).fetchone()
        elapsed_row = conn.execute(
            "SELECT name FROM platform_spans WHERE name=?",
            ("cold-start",),
        ).fetchone()
    finally:
        conn.close()
    assert span_row is not None
    assert str(span_row[0]) == "error"
    assert elapsed_row is not None


def test_reader_derives_analysis_phase_bundle_from_contributing_spans(
    tmp_path: Path,
) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            _op(
                "A",
                correlation_id="A",
                spans=(
                    _span(
                        "legacy",
                        operation_id="A",
                        name="pipeline.process",
                        duration_ms=10.0,
                        counters={"files_analyzed": 2, "failed_files": 0},
                    ),
                ),
            ),
        )
        write_operation(
            conn,
            _op(
                "B",
                correlation_id="B",
                spans=(
                    _span(
                        "phase",
                        operation_id="B",
                        name="pipeline.process",
                        duration_ms=20.0,
                        counters={
                            "files_analyzed": 2,
                            "failed_files": 0,
                            "phase_parse_us": 1000,
                            "phase_unit_cfg_us": 3000,
                            "files_timed": 2,
                            "units_eligible": 3,
                        },
                    ),
                ),
            ),
        )
    finally:
        conn.close()
    conn = open_observability_store(observability_store_path(tmp_path))
    conn.row_factory = sqlite3.Row
    try:
        trace = build_trace_view(conn)
    finally:
        conn.close()

    agg = trace.aggregates
    expected_scalars = {
        "analysis_phase_source_spans": 1,
        "analysis_phase_pipeline_wall_ms": 20.0,
        "analysis_phase_worker_elapsed_total_ms": 4.0,
        "analysis_phase_files_timed": 2,
        "analysis_phase_units_eligible": 3,
    }
    actual_scalars = {key: getattr(agg, key) for key in expected_scalars}
    assert actual_scalars == expected_scalars
    assert [(row.phase, row.share_permille) for row in agg.analysis_phases] == [
        ("unit_cfg", 750),
        ("parse", 250),
    ]


def test_observability_schema_migrates_legacy_span_columns(tmp_path: Path) -> None:
    import sqlite3

    from codeclone.observability.store.schema import create_observability_schema

    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE platform_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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
                rss_mb REAL,
                rss_delta_mb REAL,
                cpu_user_ms REAL,
                cpu_system_ms REAL,
                open_fds INTEGER,
                thread_count INTEGER
            );
            CREATE TABLE platform_operations (
                operation_id TEXT PRIMARY KEY,
                parent_operation_id TEXT,
                correlation_id TEXT NOT NULL,
                surface TEXT NOT NULL,
                name TEXT NOT NULL,
                started_at_utc TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                error_kind TEXT,
                session_id TEXT,
                repo_root_digest TEXT,
                request_bytes INTEGER,
                response_bytes INTEGER,
                request_tokens INTEGER,
                response_tokens INTEGER,
                rss_mb REAL,
                rss_delta_mb REAL,
                cpu_user_ms REAL,
                cpu_system_ms REAL,
                open_fds INTEGER,
                thread_count INTEGER
            );
            """
        )
        conn.commit()
        create_observability_schema(conn)
        span_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(platform_spans)")
        }
        operation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(platform_operations)")
        }
        assert "db_fingerprints" in span_columns
        assert "peak_rss_mb" in span_columns
        assert "peak_rss_delta_mb" in span_columns
        assert "peak_rss_mb" in operation_columns
        assert "peak_rss_delta_mb" in operation_columns
    finally:
        conn.close()
