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


def test_span_cap_does_not_hang_the_drop_count_on_an_unrelated_span(
    tmp_path: Path,
) -> None:
    """Truncation is a fact about the operation, so no span may carry it.

    It used to ride the counters of whichever span happened to be retained
    last — a counter whose subject was not its span, the same shape of hole as
    the cache lane totals — and it sat behind a detail cap that no default
    response reached.
    """
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=2),
        root=tmp_path,
    )
    with operation(name="capped", surface="cli"):
        for stage in ("pipeline.discover", "pipeline.process", "pipeline.analyze"):
            with span(name=stage):
                pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        counters = [
            orjson.loads(row[0] or b"{}")
            for row in conn.execute("SELECT counters_json FROM platform_spans")
        ]
    finally:
        conn.close()
    assert len(counters) == 2
    assert all("spans_dropped" not in counter for counter in counters)
    assert _operation_retention(tmp_path)[0] == 1


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


def _retained_span_names(root: Path) -> list[str]:
    conn = open_observability_store(observability_store_path(root))
    try:
        return [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM platform_spans ORDER BY rowid"
            ).fetchall()
        ]
    finally:
        conn.close()


def _operation_retention(root: Path) -> tuple[object, object]:
    conn = open_observability_store(observability_store_path(root))
    try:
        row = conn.execute(
            "SELECT spans_dropped, span_retention_rule FROM platform_operations"
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1])


def test_span_cap_keeps_a_first_of_its_kind_span_over_a_repeated_one(
    tmp_path: Path,
) -> None:
    """A summary span closes last, so a keep-first cap loses it by construction.

    Measured on a warm 578-file CLI run: 606 spans, 579 of them one repeated
    name, and every pipeline summary span closes after index 589. The retention
    rule must spend a repetition rather than a name it has never seen.
    """
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=3),
        root=tmp_path,
    )
    with operation(name="cli.analyze", surface="cli"):
        for _ in range(3):
            with span(name="cache.backend.load_generation"):
                pass
        with span(name="cache.content_identity"):
            pass
    shutdown()

    names = _retained_span_names(tmp_path)
    assert len(names) == 3
    assert "cache.content_identity" in names
    assert names.count("cache.backend.load_generation") == 2


def test_span_cap_drops_the_incoming_span_when_no_retained_name_repeats(
    tmp_path: Path,
) -> None:
    """The other branch: with nothing repeated there is no cheaper victim, so
    the incoming span is what goes — and it is still counted as dropped."""
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=2),
        root=tmp_path,
    )
    with operation(name="cli.analyze", surface="cli"):
        with span(name="pipeline.discover"):
            pass
        with span(name="pipeline.process"):
            pass
        with span(name="pipeline.report"):
            pass
    shutdown()

    assert _retained_span_names(tmp_path) == ["pipeline.discover", "pipeline.process"]
    assert _operation_retention(tmp_path) == (1, "protect_distinct_names")


def test_truncated_operation_records_dropped_count_and_retention_rule(
    tmp_path: Path,
) -> None:
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=2),
        root=tmp_path,
    )
    with operation(name="cli.analyze", surface="cli"):
        for _ in range(5):
            with span(name="cache.backend.load_generation"):
                pass
    shutdown()

    assert _operation_retention(tmp_path) == (3, "protect_distinct_names")


def test_untruncated_operation_records_zero_dropped_and_names_no_rule(
    tmp_path: Path,
) -> None:
    """Opposite boundary: an operation inside the cap must not claim a rule
    acted on it, and must say zero rather than leave truncation unknowable."""
    bootstrap(
        ObservabilityConfig(enabled=True, max_spans_per_operation=8),
        root=tmp_path,
    )
    with operation(name="cli.analyze", surface="cli"), span(name="pipeline.discover"):
        pass
    shutdown()

    assert _operation_retention(tmp_path) == (0, None)
