# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from codeclone.controller_insights import (
    controller_audit_trail_payload,
    workspace_session_stats_payload,
)
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
