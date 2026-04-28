from __future__ import annotations

import asyncio
from typing import cast

import pytest

from codeclone.surfaces.mcp.server import build_mcp_server
from tests._contract_snapshots import load_json_snapshot


def test_mcp_tool_schema_snapshot() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    server = build_mcp_server(history_limit=4)
    tools = asyncio.run(server.list_tools())
    snapshot = [
        {
            "name": tool.name,
            "input_schema": tool.inputSchema,
        }
        for tool in sorted(tools, key=lambda item: item.name)
    ]
    expected = cast(
        "list[dict[str, object]]",
        load_json_snapshot("mcp_tool_schemas.json"),
    )
    assert snapshot == expected
