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


def _write_quality_fixture(root: Path) -> None:
    pkg = root.joinpath("pkg")
    pkg.mkdir(exist_ok=True)
    pkg.joinpath("__init__.py").write_text("", "utf-8")
    pkg.joinpath("quality.py").write_text(
        (
            "def complex_branch(flag: int) -> int:\n"
            "    total = 0\n"
            "    for item in range(flag):\n"
            "        if item % 2 == 0:\n"
            "            total += item\n"
            "        elif item % 3 == 0:\n"
            "            total -= item\n"
            "        elif item % 5 == 0:\n"
            "            total += item * 2\n"
            "        else:\n"
            "            total += 1\n"
            "    return total\n\n"
            "def unused_helper() -> int:\n"
            "    return 42\n"
        ),
        "utf-8",
    )


def test_mcp_server_exposes_expected_read_only_tools() -> None:
    _require_mcp_runtime()
    server = build_mcp_server(history_limit=4)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "analyze_repository",
        "analyze_changed_paths",
        "get_run_summary",
        "evaluate_gates",
        "get_report_section",
        "list_findings",
        "get_finding",
        "get_remediation",
        "list_hotspots",
        "compare_runs",
        "check_complexity",
        "check_clones",
        "check_coupling",
        "check_cohesion",
        "check_dead_code",
        "generate_pr_summary",
        "mark_finding_reviewed",
        "list_reviewed_findings",
    }
    for name, tool in tools.items():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is (
            name
            in {
                "get_run_summary",
                "get_report_section",
                "list_findings",
                "get_finding",
                "get_remediation",
                "list_hotspots",
                "compare_runs",
                "generate_pr_summary",
                "list_reviewed_findings",
            }
        )
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
    assert "triggers a full analysis first" in str(
        tools["check_complexity"].description
    )
    assert "triggers a full analysis first" in str(tools["check_clones"].description)


def test_mcp_server_tool_roundtrip_and_resources(tmp_path: Path) -> None:
    _require_mcp_runtime()
    _write_clone_fixture(tmp_path)
    _write_quality_fixture(tmp_path)
    server = build_mcp_server(history_limit=4)

    summary = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "analyze_repository",
                {
                    "root": str(tmp_path),
                    "respect_pyproject": False,
                    "cache_policy": "off",
                    "changed_paths": ["pkg/dup.py", "pkg/quality.py"],
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
        asyncio.run(
            server.call_tool(
                "list_findings",
                {
                    "family": "clone",
                    "detail_level": "summary",
                    "changed_paths": ["pkg/dup.py"],
                },
            )
        )
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
    latest_health_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/health"))
    )
    assert json.loads(latest_health_resource[0].content)["score"]
    latest_changed_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/changed"))
    )
    assert json.loads(latest_changed_resource[0].content)["run_id"] == run_id

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
    latest_gates_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/gates"))
    )
    assert json.loads(latest_gates_resource[0].content)["run_id"] == run_id

    report_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "meta"}))
    )
    assert report_section["codeclone_version"]
    changed_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "changed"}))
    )
    assert changed_section["changed_paths"] == ["pkg/dup.py", "pkg/quality.py"]

    finding = _structured_tool_result(
        asyncio.run(server.call_tool("get_finding", {"finding_id": first_finding_id}))
    )
    assert finding["id"] == first_finding_id
    remediation = _structured_tool_result(
        asyncio.run(
            server.call_tool("get_remediation", {"finding_id": first_finding_id})
        )
    )
    assert remediation["finding_id"] == first_finding_id

    hotspots = _structured_tool_result(
        asyncio.run(server.call_tool("list_hotspots", {"kind": "highest_priority"}))
    )
    assert cast(int, hotspots["total"]) >= 1

    complexity = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "check_complexity",
                {
                    "run_id": run_id,
                    "path": "pkg/quality.py",
                    "min_complexity": 1,
                },
            )
        )
    )
    clones = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "check_clones",
                {"run_id": run_id, "path": "pkg/dup.py"},
            )
        )
    )
    reviewed = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "mark_finding_reviewed",
                {
                    "run_id": run_id,
                    "finding_id": first_finding_id,
                    "note": "triaged",
                },
            )
        )
    )
    reviewed_items = _structured_tool_result(
        asyncio.run(server.call_tool("list_reviewed_findings", {"run_id": run_id}))
    )
    pr_summary = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "generate_pr_summary",
                {
                    "run_id": run_id,
                    "changed_paths": ["pkg/dup.py"],
                    "format": "markdown",
                },
            )
        )
    )
    assert complexity["check"] == "complexity"
    assert cast(int, clones["total"]) >= 1
    assert reviewed["reviewed"] is True
    assert reviewed_items["reviewed_count"] == 1
    assert "## CodeClone Summary" in str(pr_summary["content"])

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

    schema_resource = list(asyncio.run(server.read_resource("codeclone://schema")))
    schema_payload = json.loads(schema_resource[0].content)
    assert schema_payload["title"] == "CodeCloneCanonicalReport"
    assert "report_schema_version" in schema_payload["properties"]


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
    def _boom() -> tuple[object, object, object]:
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
