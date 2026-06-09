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
            name="memory.semantic.reindex",
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
