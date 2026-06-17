# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from codeclone.audit.events import EVENT_PATCH_VERIFIED, AuditEvent, repo_root_digest
from codeclone.audit.reader import read_audit_summary
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.controller_insights import (
    controller_audit_trail_payload,
    workspace_session_stats_payload,
)
from codeclone.controller_insights.audit_trail import audit_summary_to_payload
from codeclone.surfaces.mcp import _session_insights_mixin as insights_mixin_mod
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.server import build_mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def test_workspace_session_stats_payload_shape(tmp_path: Path) -> None:
    payload = workspace_session_stats_payload(tmp_path)
    assert payload["status"] == "ok"
    assert "workspace" in payload
    assert "counts" in payload
    assert "agents" in payload
    workspace = cast(dict[str, object], payload["workspace"])
    assert workspace["root"] == str(tmp_path.resolve())


def test_controller_audit_trail_disabled_without_config(tmp_path: Path) -> None:
    payload = controller_audit_trail_payload(tmp_path)
    assert payload["status"] == "disabled"
    assert payload["events"] == []


def test_ide_governance_channel_exposes_insights_tools() -> None:
    pytest.importorskip("mcp.server.fastmcp")
    default_server = build_mcp_server(history_limit=4)
    ide_server = build_mcp_server(history_limit=4, ide_governance_channel=True)
    default_tools = {tool.name for tool in asyncio.run(default_server.list_tools())}
    ide_tools = {tool.name for tool in asyncio.run(ide_server.list_tools())}
    assert "get_workspace_session_stats" not in default_tools
    assert "get_controller_audit_trail" not in default_tools
    assert "get_workspace_session_stats" in ide_tools
    assert "get_controller_audit_trail" in ide_tools
    assert len(ide_tools) == len(default_tools) + 2


def test_insights_tools_reject_without_ide_channel(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4, ide_governance_channel=False)
    root = str(tmp_path.resolve())
    with pytest.raises(MCPServiceContractError, match="IDE-only"):
        service.get_workspace_session_stats(root=root)
    with pytest.raises(MCPServiceContractError, match="IDE-only"):
        service.get_controller_audit_trail(root=root)


def _write_audit_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\naudit_enabled = true\n",
        encoding="utf-8",
    )


def _emit_audit_event(root: Path) -> None:
    writer = SqliteAuditWriter(
        db_path=root / ".codeclone" / "db" / "audit.sqlite3",
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_VERIFIED,
                severity="info",
                repo_root_digest=repo_root_digest(root),
                agent_pid=123,
                agent_label="vscode-codeclone",
                run_id="abcdef123456",
                intent_id="intent-abcdef12-001",
                report_digest="a" * 64,
                status="accepted",
                payload={"status": "accepted"},
            )
        )
    finally:
        writer.close()


def test_controller_audit_trail_empty_when_enabled_but_no_db(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path)
    payload = controller_audit_trail_payload(tmp_path)
    assert payload["status"] == "empty"
    assert "no audit data" in str(payload["message"])


def test_controller_audit_trail_ok_when_audit_db_has_events(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path)
    _emit_audit_event(tmp_path)
    payload = controller_audit_trail_payload(tmp_path, limit=10)
    assert payload["status"] == "ok"
    assert cast(dict[str, int], payload["counts"])["total_events"] == 1
    events = cast(list[dict[str, object]], payload["events"])
    assert events[0]["event_type"] == EVENT_PATCH_VERIFIED
    assert payload["payload_footprint"] is not None


def _write_event_without_tokens(root: Path) -> None:
    from codeclone.audit.schema import ensure_schema

    db_path = root / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO controller_events "
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status, run_id, intent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt_no_tokens",
                EVENT_PATCH_VERIFIED,
                "info",
                "2026-05-26T10:00:00Z",
                "digest123",
                "test-agent",
                123,
                "accepted",
                "run123",
                "intent-test-001",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_audit_summary_to_payload_without_footprint(tmp_path: Path) -> None:
    _write_event_without_tokens(tmp_path)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    summary = read_audit_summary(db_path=db_path, limit=5)
    payload = audit_summary_to_payload(summary)
    assert payload["status"] == "ok"
    assert payload["payload_footprint"] is None
    assert cast(dict[str, object], payload["database"])["path"] == str(db_path)


def test_mcp_insights_tools_with_ide_channel(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path)
    _emit_audit_event(tmp_path)
    service = CodeCloneMCPService(history_limit=4, ide_governance_channel=True)
    root = str(tmp_path.resolve())

    stats = service.get_workspace_session_stats(root=root)
    assert stats["tool"] == "get_workspace_session_stats"
    assert stats["status"] == "ok"

    trail = service.get_controller_audit_trail(root=root, limit=5)
    assert trail["tool"] == "get_controller_audit_trail"
    assert trail["status"] == "ok"
    assert cast(dict[str, int], trail["counts"])["total_events"] == 1


def test_mcp_insights_audit_trail_limit_validation(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4, ide_governance_channel=True)
    root = str(tmp_path.resolve())
    with pytest.raises(MCPServiceContractError, match="limit must be between"):
        service.get_controller_audit_trail(root=root, limit=0)
    with pytest.raises(MCPServiceContractError, match="limit must be between"):
        service.get_controller_audit_trail(root=root, limit=201)


def test_mcp_insights_session_stats_surfaces_reader_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4, ide_governance_channel=True)
    root = str(tmp_path.resolve())

    def _boom(_root_path: Path) -> dict[str, object]:
        raise RuntimeError("stats backend down")

    monkeypatch.setattr(insights_mixin_mod, "workspace_session_stats_payload", _boom)
    with pytest.raises(
        MCPServiceContractError, match="Failed to read workspace session stats"
    ):
        service.get_workspace_session_stats(root=root)
