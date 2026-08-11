# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The observer must not evict the runtime it is there to observe.

``window="latest"`` used to mean "the last N operations of any kind", and
``query_platform_observability`` is itself an instrumented MCP tool — so reading
the instrument consumed the slots holding the evidence it had just pointed at.
These tests pin the two-plane split: runtime operations and observer operations
live in separate windows with separate budgets, the runtime plane is the
default, and rows written before the plane mark existed are reported as
unattributed rather than silently counted as runtime.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.models import OperationRecord
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
from codeclone.observability.vocabulary import (
    PLANE_OBSERVER,
    PLANE_RUNTIME,
    resolve_operation_plane,
)

_OBSERVER_OPERATION = "mcp.query_platform_observability"
_RUNTIME_OPERATION = "mcp.analyze_repository"


def _operation_record(
    operation_id: str,
    *,
    name: str,
    started_at_utc: str,
    plane: str,
) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        correlation_id=operation_id,
        surface="mcp",
        name=name,
        started_at_utc=started_at_utc,
        duration_ms=1.0,
        status="ok",
        response_bytes=100,
        response_tokens=25,
        plane=plane,
    )


def _timestamp(index: int) -> str:
    return f"2026-08-11T00:{index // 60:02d}:{index % 60:02d}.000000Z"


def _seed(
    root: Path,
    *,
    runtime_operations: int,
    observer_operations: int,
) -> None:
    conn = open_observability_store(observability_store_path(root))
    try:
        index = 0
        for ordinal in range(runtime_operations):
            write_operation(
                conn,
                _operation_record(
                    f"runtime-{ordinal:03d}",
                    name=_RUNTIME_OPERATION,
                    started_at_utc=_timestamp(index),
                    plane=PLANE_RUNTIME,
                ),
            )
            index += 1
        for ordinal in range(observer_operations):
            write_operation(
                conn,
                _operation_record(
                    f"observer-{ordinal:03d}",
                    name=_OBSERVER_OPERATION,
                    started_at_utc=_timestamp(index),
                    plane=PLANE_OBSERVER,
                ),
            )
            index += 1
    finally:
        conn.close()


def _assert_unattributed_warning(payload: dict[str, object]) -> None:
    warnings = payload.get("warnings", [])
    assert isinstance(warnings, list)
    assert any("unattributed" in str(item) for item in warnings)


def _operation_names(root: Path, *, window: str) -> list[str]:
    payload = query_platform_observability(
        root=root,
        section="mcp_tool_matrix",
        detail_level="normal",
        limit=100,
        window=window,
    )
    rows = payload["rows"]
    assert isinstance(rows, list)
    return sorted(str(row["tool"]) for row in rows)


def test_observer_calls_do_not_evict_runtime_from_the_default_window(
    tmp_path: Path,
) -> None:
    # 20 runtime operations then 10 observer calls: under one shared window the
    # observer's own calls are the newest and push half the runtime out.
    _seed(tmp_path, runtime_operations=20, observer_operations=10)

    payload = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="latest",
    )

    assert payload["operations"] == 20
    assert _operation_names(tmp_path, window="latest") == [_RUNTIME_OPERATION]


def test_default_window_is_the_runtime_plane(tmp_path: Path) -> None:
    _seed(tmp_path, runtime_operations=1, observer_operations=1)

    payload = query_platform_observability(root=tmp_path, section="summary")

    assert payload["plane"] == PLANE_RUNTIME
    assert payload["window"] == "latest"


def test_observer_plane_is_readable_on_request(tmp_path: Path) -> None:
    _seed(tmp_path, runtime_operations=3, observer_operations=2)

    observer = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="observer",
    )
    everything = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="all",
    )

    assert observer["plane"] == PLANE_OBSERVER
    assert observer["operations"] == 2
    assert everything["plane"] == "all"
    assert everything["operations"] == 5
    assert _operation_names(tmp_path, window="observer") == [_OBSERVER_OPERATION]
    assert _operation_names(tmp_path, window="all") == [
        _RUNTIME_OPERATION,
        _OBSERVER_OPERATION,
    ]


def test_each_plane_gets_its_own_window_budget(tmp_path: Path) -> None:
    # 30 of each: a shared 20-slot window over "all" would return the 20 newest
    # operations — all observer. Per-plane budgets return 20 of each.
    _seed(tmp_path, runtime_operations=30, observer_operations=30)

    conn = open_observability_store_readonly(tmp_path)
    assert conn is not None
    try:
        trace = build_trace_view(conn, plane="all")
    finally:
        conn.close()

    planes = [op.plane for op in trace.correlated_operations]
    assert planes.count(PLANE_RUNTIME) == 20
    assert planes.count(PLANE_OBSERVER) == 20


def test_unmarked_rows_are_reported_unattributed_not_runtime(tmp_path: Path) -> None:
    _seed(tmp_path, runtime_operations=2, observer_operations=0)
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        conn.execute(
            "UPDATE platform_operations SET plane=NULL WHERE operation_id=?",
            ("runtime-000",),
        )
        conn.commit()
    finally:
        conn.close()

    runtime = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="latest",
    )
    everything = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="all",
    )

    assert runtime["operations"] == 1
    assert runtime["plane_coverage"] == {
        "plane_column_available": True,
        "runtime": 1,
        "observer": 0,
        "unattributed": 1,
    }
    assert everything["operations"] == 2
    _assert_unattributed_warning(runtime)


def test_store_without_the_plane_column_refuses_to_claim_runtime(
    tmp_path: Path,
) -> None:
    # A store written by a build that predates the plane mark: every row is
    # unattributed, and the reader must say so instead of inventing a plane.
    path = observability_store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE platform_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
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
            INSERT INTO platform_operations(
                operation_id, correlation_id, surface, name,
                started_at_utc, duration_ms, status)
            VALUES('legacy', 'legacy', 'mcp', 'mcp.analyze_repository',
                   '2026-08-01T00:00:00.000000Z', 1.0, 'ok');
            """
        )
        conn.commit()
    finally:
        conn.close()

    payload = query_platform_observability(
        root=tmp_path,
        section="summary",
        window="latest",
    )

    assert payload["plane_coverage"] == {
        "plane_column_available": False,
        "runtime": 0,
        "observer": 0,
        "unattributed": 1,
    }
    assert payload["operations"] == 0
    _assert_unattributed_warning(payload)


def test_observer_operations_do_not_consume_the_runtime_persist_budget(
    tmp_path: Path,
) -> None:
    # max_operations_per_process is a retention bound. Shared, the observer
    # spends it and the runtime operations that follow are never persisted.
    bootstrap(
        ObservabilityConfig(enabled=True, max_operations_per_process=2),
        root=tmp_path,
    )
    try:
        for _ in range(2):
            with operation(name=_OBSERVER_OPERATION, surface="mcp"):
                pass
        for _ in range(2):
            with operation(name=_RUNTIME_OPERATION, surface="mcp"):
                pass
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = dict(
            conn.execute(
                "SELECT plane, COUNT(*) FROM platform_operations GROUP BY plane"
            ).fetchall()
        )
    finally:
        conn.close()
    assert rows == {PLANE_RUNTIME: 2, PLANE_OBSERVER: 2}


def test_plane_is_resolved_from_the_operation_name(tmp_path: Path) -> None:
    assert resolve_operation_plane(_OBSERVER_OPERATION) == PLANE_OBSERVER
    assert resolve_operation_plane(_RUNTIME_OPERATION) == PLANE_RUNTIME

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name=_OBSERVER_OPERATION, surface="mcp"):
            pass
        with operation(name="cli.analyze", surface="cli"):
            pass
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = dict(
            conn.execute("SELECT name, plane FROM platform_operations").fetchall()
        )
    finally:
        conn.close()
    assert rows == {
        _OBSERVER_OPERATION: PLANE_OBSERVER,
        "cli.analyze": PLANE_RUNTIME,
    }
