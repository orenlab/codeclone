# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path

import orjson
import pytest

from codeclone.config.observability import ObservabilityConfig
from codeclone.observability import bootstrap, record_db_query, shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.surfaces.mcp.server import _instrument_tool


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def _sample_tool(root: str, limit: int = 5) -> dict[str, object]:
    return {"root": root, "limit": limit, "items": list(range(limit))}


def test_registrar_records_operation_with_payload_sizes(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), session_id="mcp-test")
    wrapped = _instrument_tool(_sample_tool)
    try:
        result = wrapped(root=str(tmp_path), limit=3)
    finally:
        shutdown()
    assert result == {"root": str(tmp_path), "limit": 3, "items": [0, 1, 2]}

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT surface, name, session_id, request_bytes, response_bytes, "
            "request_tokens, response_tokens FROM platform_operations"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "mcp"
    assert row[1] == "mcp._sample_tool"
    assert row[2] == "mcp-test"
    # Payload sizes captured on both directions (bytes + tokens, all positive).
    assert row[3] > 0
    assert row[4] > 0
    assert row[5] > 0
    assert row[6] > 0
    # Response is the larger payload (it carries the items list).
    assert row[4] > row[3]


def test_registrar_attributes_db_queries_to_a_span(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), session_id="mcp-test")

    def _db_tool(root: str) -> dict[str, object]:
        # Emulate the sqlite trace callback firing during the handler's DB work.
        record_db_query("SELECT 1")
        record_db_query("INSERT INTO t (x) VALUES (1)")
        return {"root": root}

    wrapped = _instrument_tool(_db_tool)
    try:
        wrapped(root=str(tmp_path))
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT s.counters_json FROM platform_spans s "
            "JOIN platform_operations o ON o.operation_id = s.operation_id "
            "WHERE o.name = 'mcp._db_tool'"
        ).fetchall()
    finally:
        conn.close()
    # The wrapper opens a root span, so the handler's DB queries are attributed
    # to the operation instead of being dropped for lack of an active span.
    counters = [orjson.loads(row[0]) for row in rows]
    assert sum(c.get("db_queries", 0) for c in counters) == 2
    assert sum(c.get("db_writes", 0) for c in counters) == 1


def test_registrar_preserves_signature() -> None:
    wrapped = _instrument_tool(_sample_tool)
    # The wrapper exposes the same (resolved) parameters as the original so
    # FastMCP builds an identical input schema.
    assert inspect.signature(wrapped) == inspect.signature(_sample_tool, eval_str=True)
    assert getattr(wrapped, "__name__", "") == "_sample_tool"


def test_registrar_inert_when_disabled(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=False))
    wrapped = _instrument_tool(_sample_tool)
    result = wrapped(root=str(tmp_path), limit=2)
    assert result == {"root": str(tmp_path), "limit": 2, "items": [0, 1]}
    assert not observability_store_path(tmp_path).exists()
