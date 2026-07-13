# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import orjson
import pytest

from codeclone.models import ObservabilityConfig
from codeclone.observability import (
    bootstrap,
    is_observability_enabled,
    operation,
    record_counter,
    shutdown,
    span,
)
from codeclone.observability.models import OperationRecord
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def test_disabled_is_inert_and_imports_no_store() -> None:
    for module in list(sys.modules):
        if module.startswith("codeclone.observability.store"):
            sys.modules.pop(module, None)
    sys.modules.pop("psutil", None)

    bootstrap(ObservabilityConfig(enabled=False))
    assert is_observability_enabled() is False
    # The full handle API must be callable (and inert) when disabled.
    with operation(name="x", surface="cli") as op:
        op.set_request(request_bytes=5, request_tokens=1)
        op.set_response(response_bytes=10, response_tokens=2)
        with span(name="pipeline.process", reason_kind="content_changed") as sp:
            sp.add_counter("embedded", 3)
            sp.set_counter("skipped_unchanged", 0)
            sp.set_reason_kind("model_changed")

    importlib.import_module("codeclone.analysis.units")
    importlib.import_module("codeclone.core.parallelism")

    assert not any(m.startswith("codeclone.observability.store") for m in sys.modules)
    assert "psutil" not in sys.modules


def test_enabled_persists_operation_and_nested_spans(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path, session_id="sess1")
    with operation(name="finish", surface="mcp") as op:
        op.set_response(response_bytes=820, response_tokens=120)
        with span(
            name="memory.semantic.rebuild",
            reason_kind="schema_version_changed",
        ) as sp:
            sp.set_counter("embedded", 1423)
            with span(name="memory.semantic.embed"):
                pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        op_row = conn.execute(
            "SELECT name, surface, session_id, response_bytes FROM platform_operations"
        ).fetchall()
        assert op_row == [("finish", "mcp", "sess1", 820)]
        rows = conn.execute(
            "SELECT name, span_id, parent_span_id, reason_kind FROM platform_spans"
        ).fetchall()
        by_name = {row[0]: row for row in rows}
        assert set(by_name) == {"memory.semantic.rebuild", "memory.semantic.embed"}
        assert by_name["memory.semantic.rebuild"][3] == "schema_version_changed"
        # Nested span links to its parent span.
        assert (
            by_name["memory.semantic.embed"][2]
            == (by_name["memory.semantic.rebuild"][1])
        )
    finally:
        conn.close()


def test_record_counter_attributes_to_active_span(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with operation(name="search", surface="mcp"), span(name="retrieval.embed_query"):
        record_counter("retrieval.fts_hits", 3)
        record_counter("retrieval.fts_hits", 2)  # accumulates onto the same key
        record_counter("retrieval.vector_memory_hits")  # default value 1
    # Outside any span the counter is inert (no raise, nothing recorded).
    record_counter("retrieval.fts_hits", 99)
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        (counters_json,) = conn.execute(
            "SELECT counters_json FROM platform_spans "
            "WHERE name='retrieval.embed_query'"
        ).fetchone()
    finally:
        conn.close()
    counters = orjson.loads(counters_json)
    assert counters["retrieval.fts_hits"] == 5
    assert counters["retrieval.vector_memory_hits"] == 1


def test_cross_process_correlation_and_parent(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with operation(name="A", surface="mcp", correlation_id="corrX") as a:
        a_id = a.operation_id
    with operation(
        name="B", surface="memory", parent_operation_id=a_id, correlation_id="corrX"
    ):
        pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT parent_operation_id, correlation_id "
            "FROM platform_operations WHERE name='B'"
        ).fetchone()
        assert row == (a_id, "corrX")
    finally:
        conn.close()


def test_operation_records_error_status(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with pytest.raises(ValueError, match="nope"), operation(name="boom", surface="cli"):
        raise ValueError("nope")
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT status, error_kind FROM platform_operations WHERE name='boom'"
        ).fetchone()
        assert row == ("error", "ValueError")
    finally:
        conn.close()


def test_record_elapsed_span_is_noop_without_active_operation(tmp_path: Path) -> None:
    from codeclone.observability import bootstrap, record_elapsed_span, shutdown

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        record_elapsed_span(
            "memory.projection.worker_bootstrap",
            started_at_utc="2026-01-01T00:00:00Z",
            duration_ms=1.0,
        )
    finally:
        shutdown()


def test_runtime_optional_payload_root_and_empty_sql_edges(tmp_path: Path) -> None:
    from codeclone.observability import runtime

    bootstrap(ObservabilityConfig(enabled=True), session_id="session")
    with operation(name="rootless", surface="mcp") as op:
        op.set_request(request_bytes=1)
        op.set_request(request_tokens=2)
        op.set_response(response_bytes=3)
        op.set_response(response_tokens=4)
        with span(name="pipeline.process"):
            runtime.record_db_query("")

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    runtime.bind_root(first_root)
    runtime.bind_root(second_root)
    with operation(name="rooted", surface="mcp"):
        pass
    shutdown()

    assert observability_store_path(first_root).exists()
    assert not observability_store_path(second_root).exists()

    bootstrap(ObservabilityConfig(enabled=False))
    runtime.bind_root(tmp_path / "disabled")

    active = runtime._ActiveRuntime(
        ObservabilityConfig(enabled=True),
        root=tmp_path,
    )
    active.close()
    active._conn = object()
    active.close()
    assert active._conn is None


def test_span_cap_records_dropped_count_on_final_retained_span(
    tmp_path: Path,
) -> None:
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=2),
        root=tmp_path,
    )
    with operation(name="capped", surface="cli"):
        with span(name="pipeline.discover"):
            pass
        with span(name="pipeline.process"):
            pass
        with span(name="pipeline.analyze"):
            pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT name, counters_json FROM platform_spans "
            "ORDER BY started_at_utc, span_id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    dropped = sum(orjson.loads(row[1] or b"{}").get("spans_dropped", 0) for row in rows)
    assert dropped == 1


def test_process_operation_write_cap_is_enforced(tmp_path: Path) -> None:
    bootstrap(
        ObservabilityConfig(enabled=True, max_operations_per_process=2),
        root=tmp_path,
    )
    for name in ("one", "two", "three"):
        with operation(name=name, surface="cli"):
            pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM platform_operations").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_bootstrap_runs_retention_gc(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="expired",
                correlation_id="expired",
                surface="cli",
                name="expired",
                started_at_utc="2000-01-01T00:00:00Z",
                duration_ms=1.0,
                status="ok",
            ),
        )
    finally:
        conn.close()

    bootstrap(
        ObservabilityConfig(enabled=True, retention_days=1),
        root=tmp_path,
    )
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM platform_operations").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
