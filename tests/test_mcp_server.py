# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import builtins
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from codeclone import mcp_server
from codeclone.mcp_server import MCPDependencyError, build_mcp_server


def _structured_tool_result(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return result
    assert isinstance(result, tuple)
    assert len(result) == 2
    payload = result[1]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _require_mcp_runtime() -> None:
    pytest.importorskip("mcp.server.fastmcp")


def _write_clone_fixture(root: Path) -> None:
    root.joinpath("pkg").mkdir()
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "dup.py").write_text(
        (
            "def alpha(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    total += 5\n"
            "    total += 6\n"
            "    total += 7\n"
            "    total += 8\n"
            "    return total\n\n"
            "def beta(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    total += 5\n"
            "    total += 6\n"
            "    total += 7\n"
            "    total += 8\n"
            "    return total\n"
        ),
        "utf-8",
    )


def test_mcp_server_exposes_expected_read_only_tools() -> None:
    _require_mcp_runtime()
    server = build_mcp_server(history_limit=4)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "analyze_repository",
        "get_run_summary",
        "evaluate_gates",
        "get_report_section",
        "list_findings",
        "get_finding",
        "list_hotspots",
    }
    for tool in tools.values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True


def test_mcp_server_tool_roundtrip_and_resources(tmp_path: Path) -> None:
    _require_mcp_runtime()
    _write_clone_fixture(tmp_path)
    server = build_mcp_server(history_limit=4)

    summary = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "analyze_repository",
                {
                    "root": str(tmp_path),
                    "respect_pyproject": False,
                    "cache_policy": "off",
                },
            )
        )
    )
    run_id = str(summary["run_id"])

    latest = _structured_tool_result(
        asyncio.run(server.call_tool("get_run_summary", {}))
    )
    assert latest["run_id"] == run_id

    findings_result = _structured_tool_result(
        asyncio.run(server.call_tool("list_findings", {"family": "clone"}))
    )
    assert cast(int, findings_result["total"]) >= 1

    latest_summary_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/summary"))
    )
    assert latest_summary_resource
    latest_summary_text = latest_summary_resource[0].content
    latest_summary = json.loads(latest_summary_text)
    assert latest_summary["run_id"] == run_id

    latest_report_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/report.json"))
    )
    assert (
        json.loads(latest_report_resource[0].content)["report_schema_version"] == "2.1"
    )

    report_resource = list(
        asyncio.run(server.read_resource(f"codeclone://runs/{run_id}/report.json"))
    )
    assert report_resource
    report_payload = json.loads(report_resource[0].content)
    assert report_payload["report_schema_version"] == "2.1"

    finding_items = cast("list[dict[str, object]]", findings_result["items"])
    first_finding_id = str(finding_items[0]["id"])

    gate_result = _structured_tool_result(
        asyncio.run(server.call_tool("evaluate_gates", {"fail_threshold": 0}))
    )
    assert gate_result["would_fail"] is True

    report_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "meta"}))
    )
    assert report_section["codeclone_version"]

    finding = _structured_tool_result(
        asyncio.run(server.call_tool("get_finding", {"finding_id": first_finding_id}))
    )
    assert finding["id"] == first_finding_id

    hotspots = _structured_tool_result(
        asyncio.run(server.call_tool("list_hotspots", {"kind": "highest_spread"}))
    )
    assert cast(int, hotspots["total"]) >= 1

    run_summary_resource = list(
        asyncio.run(server.read_resource(f"codeclone://runs/{run_id}/summary"))
    )
    assert json.loads(run_summary_resource[0].content)["run_id"] == run_id

    finding_resource = list(
        asyncio.run(
            server.read_resource(
                f"codeclone://runs/{run_id}/findings/{first_finding_id}"
            )
        )
    )
    assert json.loads(finding_resource[0].content)["id"] == first_finding_id


def test_mcp_server_parser_defaults_and_main_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = mcp_server.build_parser()
    args = parser.parse_args([])
    assert args.transport == "stdio"
    assert args.history_limit == 16
    assert args.json_response is True
    assert args.stateless_http is True
    assert args.log_level == "INFO"

    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    def _fake_build_mcp_server(**kwargs: object) -> _FakeServer:
        captured["kwargs"] = kwargs
        return _FakeServer()

    monkeypatch.setattr(mcp_server, "build_mcp_server", _fake_build_mcp_server)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone-mcp",
            "--transport",
            "streamable-http",
            "--port",
            "9000",
            "--history-limit",
            "8",
        ],
    )

    mcp_server.main()

    assert captured["transport"] == "streamable-http"
    kwargs = cast("dict[str, object]", captured["kwargs"])
    assert kwargs["port"] == 9000
    assert kwargs["history_limit"] == 8


def test_mcp_server_main_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom() -> tuple[object, object]:
        raise MCPDependencyError("install codeclone[mcp]")

    monkeypatch.setattr(mcp_server, "_load_mcp_runtime", _boom)
    monkeypatch.setattr(sys, "argv", ["codeclone-mcp"])

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main()

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "codeclone[mcp]" in err


def test_mcp_server_load_runtime_wraps_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _fake_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name.startswith("mcp.server.fastmcp"):
            raise ImportError("missing mcp")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(MCPDependencyError):
        mcp_server._load_mcp_runtime()


def test_mcp_server_main_swallows_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeServer:
        def run(self, *, transport: str) -> None:
            raise KeyboardInterrupt()

    monkeypatch.setattr(
        mcp_server,
        "build_mcp_server",
        lambda **_kwargs: _FakeServer(),
    )
    monkeypatch.setattr(
        sys, "argv", ["codeclone-mcp", "--transport", "streamable-http"]
    )

    mcp_server.main()
