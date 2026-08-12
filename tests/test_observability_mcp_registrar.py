# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Iterator
from pathlib import Path

import orjson
import pytest

from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, record_db_query, shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.vocabulary import _MCP_TOOL_NAMES, validate_span_name
from codeclone.surfaces.mcp._context_governance import (
    CONTEXT_GOVERNANCE_CONTRACT_VERSION,
    CONTEXT_GOVERNANCE_ESTIMATOR,
)
from codeclone.surfaces.mcp.server import _instrument_tool, build_mcp_server


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def get_run_summary(root: str, limit: int = 5) -> dict[str, object]:
    return {"root": root, "limit": limit, "items": list(range(limit))}


def get_relevant_memory(root: str) -> dict[str, object]:
    return {
        "root": root,
        "items": list(range(100)),
        "context_governance": {
            "contract_version": CONTEXT_GOVERNANCE_CONTRACT_VERSION,
            "estimator": CONTEXT_GOVERNANCE_ESTIMATOR,
            "estimated": 17,
            "mode": "observe",
        },
    }


def test_registrar_records_operation_with_payload_sizes(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), session_id="mcp-test")
    wrapped = _instrument_tool(get_run_summary)
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
    assert row[1] == "mcp.get_run_summary"
    assert row[2] == "mcp-test"
    # Payload sizes captured on both directions (bytes + context units).
    assert row[3] > 0
    assert row[4] > 0
    assert row[5] > 0
    assert row[6] > 0
    # Response is the larger payload (it carries the items list).
    assert row[4] > row[3]


def test_registrar_uses_context_governance_estimate_for_response_tokens(
    tmp_path: Path,
) -> None:
    bootstrap(ObservabilityConfig(enabled=True), session_id="mcp-test")
    wrapped = _instrument_tool(get_relevant_memory)
    try:
        wrapped(root=str(tmp_path))
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT response_bytes, response_tokens FROM platform_operations "
            "WHERE name = 'mcp.get_relevant_memory'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] > 0
    assert row[1] == 17


def test_registrar_attributes_db_queries_to_a_span(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), session_id="mcp-test")

    def check_patch_contract(root: str) -> dict[str, object]:
        # Emulate the sqlite trace callback firing during the handler's DB work.
        record_db_query("SELECT 1")
        record_db_query("INSERT INTO t (x) VALUES (1)")
        return {"root": root}

    wrapped = _instrument_tool(check_patch_contract)
    try:
        wrapped(root=str(tmp_path))
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT s.counters_json FROM platform_spans s "
            "JOIN platform_operations o ON o.operation_id = s.operation_id "
            "WHERE o.name = 'mcp.check_patch_contract'"
        ).fetchall()
    finally:
        conn.close()
    # The wrapper opens a root span, so the handler's DB queries are attributed
    # to the operation instead of being dropped for lack of an active span.
    counters = [orjson.loads(row[0]) for row in rows]
    assert sum(c.get("db_queries", 0) for c in counters) == 2
    assert sum(c.get("db_writes", 0) for c in counters) == 1


def test_registrar_preserves_signature() -> None:
    wrapped = _instrument_tool(get_run_summary)
    # The wrapper exposes the same (resolved) parameters as the original so
    # FastMCP builds an identical input schema.
    assert inspect.signature(wrapped) == inspect.signature(
        get_run_summary, eval_str=True
    )
    assert getattr(wrapped, "__name__", "") == "get_run_summary"


def test_registrar_inert_when_disabled(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=False))
    wrapped = _instrument_tool(get_run_summary)
    result = wrapped(root=str(tmp_path), limit=2)
    assert result == {"root": str(tmp_path), "limit": 2, "items": [0, 1]}
    assert not observability_store_path(tmp_path).exists()


@functools.cache
def _registered_mcp_tools() -> frozenset[str]:
    """Every tool name a caller can reach, read out of the servers themselves.

    Both governance channels, because ``get_workspace_session_stats`` and
    ``get_controller_audit_trail`` are registered only when
    ``ide_governance_channel`` is on: absent from the default registry without
    being withdrawn. Checking against the default registry alone would read
    them as dead names and invite their removal.
    """
    pytest.importorskip("mcp.server.fastmcp")
    names: set[str] = set()
    try:
        for governance_channel in (False, True):
            server = build_mcp_server(
                history_limit=4,
                ide_governance_channel=governance_channel,
            )
            names |= {tool.name for tool in asyncio.run(server.list_tools())}
    finally:
        # build_mcp_server bootstraps the process-wide observer; hand the
        # runtime back in the state the other tests here expect.
        shutdown()
    return frozenset(names)


def test_every_registered_tool_has_a_span_name() -> None:
    """A registered tool with no span name does not run at all.

    ``_instrument_tool`` opens ``span(name=f"mcp.{tool_name}")`` around every
    handler and ``validate_span_name`` is unconditional, so a name missing from
    the vocabulary is not lost telemetry — the tool raises before it does any
    work and the caller is told to "update the reviewed vocabulary".
    ``check_authority`` shipped that way: registered, called, and refused for
    as long as observability was on, while a suite of 6175 tests stayed green.
    This hands the live registry to the same validator the wrapper calls, so
    the failure here is the failure a user gets.
    """
    registered = _registered_mcp_tools()
    assert registered, "no tool was registered, so no name reached the validator"
    for tool_name in sorted(registered):
        validate_span_name(f"mcp.{tool_name}")


def test_no_mcp_span_name_outlives_the_tool_it_names() -> None:
    """The opposite direction, and the opposite consequence.

    A name for a tool nobody can call breaks nothing at the call edge: it just
    never appears in a trace, and the vocabulary quietly documents a server
    that no longer exists — until someone reads it as the inventory it looks
    like. Neither side keeps a second list of tool names: this compares the
    declared set to the registry a caller actually reaches.
    """
    registered = _registered_mcp_tools()
    assert registered, "no tool was registered, so nothing was compared"
    assert sorted(set(_MCP_TOOL_NAMES) - registered) == []
