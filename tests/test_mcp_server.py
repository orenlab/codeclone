# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import asyncio
import builtins
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from codeclone import mcp_server
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.mcp_server import MCPDependencyError, build_mcp_server


def _structured_tool_result(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return result
    assert isinstance(result, tuple)
    assert len(result) == 2
    payload = result[1]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _mapping_child(payload: Mapping[str, object], key: str) -> dict[str, object]:
    return cast("dict[str, object]", payload[key])


def _summary_registry(payload: Mapping[str, object]) -> dict[str, object]:
    return _mapping_child(_mapping_child(payload, "inventory"), "file_registry")


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
        "clear_session_runs",
        "get_run_summary",
        "get_production_triage",
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
                "check_complexity",
                "check_clones",
                "check_coupling",
                "check_cohesion",
                "check_dead_code",
                "get_run_summary",
                "get_production_triage",
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
    assert "cache_policy='off'" in str(tools["analyze_repository"].description)
    assert "cache_policy='off'" in str(tools["analyze_changed_paths"].description)
    assert "Use analyze_repository first" in str(tools["check_complexity"].description)
    assert "Use analyze_repository first" in str(tools["check_clones"].description)


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
    changed_summary = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "analyze_changed_paths",
                {
                    "root": str(tmp_path),
                    "respect_pyproject": False,
                    "cache_policy": "off",
                    "changed_paths": ["pkg/dup.py"],
                },
            )
        )
    )
    run_id = str(summary["run_id"])
    changed_run_id = str(changed_summary["run_id"])
    changed_registry = _summary_registry(changed_summary)
    assert cast(int, changed_registry["count"]) >= 1
    assert "items" not in changed_registry

    latest = _structured_tool_result(
        asyncio.run(server.call_tool("get_run_summary", {}))
    )
    assert latest["run_id"] == run_id
    latest_registry = _summary_registry(latest)
    assert cast(int, latest_registry["count"]) >= 1
    assert "items" not in latest_registry

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
    assert findings_result["base_uri"] == tmp_path.as_uri()
    assert cast(int, findings_result["total"]) >= 1
    summary_finding = cast("list[dict[str, object]]", findings_result["items"])[0]
    assert "priority_factors" not in summary_finding
    assert all(
        set(cast("dict[str, object]", location)) <= {"file", "line"}
        for location in cast("list[object]", summary_finding["locations"])
    )

    latest_summary_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/summary"))
    )
    assert latest_summary_resource
    latest_summary_text = latest_summary_resource[0].content
    latest_summary = json.loads(latest_summary_text)
    assert latest_summary["run_id"] == run_id
    latest_summary_registry = _summary_registry(latest_summary)
    assert cast(int, latest_summary_registry["count"]) >= 1
    assert "items" not in latest_summary_registry

    production_triage = _structured_tool_result(
        asyncio.run(server.call_tool("get_production_triage", {}))
    )
    assert production_triage["run_id"] == run_id
    assert _mapping_child(production_triage, "cache")["effective_freshness"]

    latest_report_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/report.json"))
    )
    assert (
        json.loads(latest_report_resource[0].content)["report_schema_version"]
        == REPORT_SCHEMA_VERSION
    )
    latest_health_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/health"))
    )
    assert json.loads(latest_health_resource[0].content)["score"]
    latest_changed_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/changed"))
    )
    latest_changed_payload = json.loads(latest_changed_resource[0].content)
    assert latest_changed_payload["run_id"] == changed_run_id
    assert latest_changed_payload["changed_paths"] == changed_summary["changed_paths"]
    latest_triage_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/triage"))
    )
    assert json.loads(latest_triage_resource[0].content)["run_id"] == run_id

    report_resource = list(
        asyncio.run(server.read_resource(f"codeclone://runs/{run_id}/report.json"))
    )
    assert report_resource
    report_payload = json.loads(report_resource[0].content)
    assert report_payload["report_schema_version"] == REPORT_SCHEMA_VERSION

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
    assert cast("dict[str, object]", report_section["analysis_thresholds"])[
        "design_findings"
    ]
    metrics_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "metrics"}))
    )
    assert "summary" in metrics_section
    assert "families" not in metrics_section
    metrics_detail_section = _structured_tool_result(
        asyncio.run(
            server.call_tool("get_report_section", {"section": "metrics_detail"})
        )
    )
    assert "families" in metrics_detail_section
    changed_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "changed"}))
    )
    assert changed_section["changed_paths"] == changed_summary["changed_paths"]

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
    comparison = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "compare_runs",
                {
                    "run_id_before": run_id,
                    "run_id_after": changed_run_id,
                    "focus": "all",
                },
            )
        )
    )
    assert hotspots["base_uri"] == tmp_path.as_uri()
    assert cast(int, hotspots["total"]) >= 1
    assert comparison["summary"]

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
    coupling = _structured_tool_result(
        asyncio.run(server.call_tool("check_coupling", {"run_id": run_id}))
    )
    cohesion = _structured_tool_result(
        asyncio.run(server.call_tool("check_cohesion", {"run_id": run_id}))
    )
    dead_code = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "check_dead_code",
                {"run_id": run_id, "path": "pkg/quality.py"},
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
    assert complexity["base_uri"] == tmp_path.as_uri()
    assert cast(int, clones["total"]) >= 1
    assert clones["base_uri"] == tmp_path.as_uri()
    assert coupling["check"] == "coupling"
    assert coupling["base_uri"] == tmp_path.as_uri()
    assert cohesion["check"] == "cohesion"
    assert cohesion["base_uri"] == tmp_path.as_uri()
    assert dead_code["check"] == "dead_code"
    assert dead_code["base_uri"] == tmp_path.as_uri()
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

    cleared = _structured_tool_result(
        asyncio.run(server.call_tool("clear_session_runs", {}))
    )
    assert cast(int, cleared["cleared_runs"]) >= 1
    assert run_id in cast("list[str]", cleared["cleared_run_ids"])
    from mcp.server.fastmcp.exceptions import ResourceError

    with pytest.raises(ResourceError):
        list(asyncio.run(server.read_resource("codeclone://latest/summary")))


def test_mcp_server_parser_defaults_and_main_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = mcp_server.build_parser()
    args = parser.parse_args([])
    assert args.transport == "stdio"
    assert args.history_limit == 4
    assert args.json_response is True
    assert args.stateless_http is True
    assert args.log_level == "INFO"
    assert args.allow_remote is False

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


def test_mcp_server_parser_rejects_excessive_history_limit() -> None:
    parser = mcp_server.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--history-limit", "11"])


def test_mcp_server_main_rejects_non_loopback_host_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main()

    assert exc_info.value.code == 2
    assert "without --allow-remote" in capsys.readouterr().err


def test_mcp_server_main_allows_non_loopback_host_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    monkeypatch.setattr(mcp_server, "build_mcp_server", lambda **kwargs: _FakeServer())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--allow-remote",
        ],
    )

    mcp_server.main()

    assert captured["transport"] == "streamable-http"


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


def test_mcp_server_history_limit_arg_rejects_non_integer() -> None:
    with pytest.raises(
        argparse.ArgumentTypeError, match="history limit must be an integer"
    ):
        mcp_server._history_limit_arg("oops")


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


def test_mcp_server_host_loopback_detection() -> None:
    assert mcp_server._host_is_loopback("") is False
    assert mcp_server._host_is_loopback("127.0.0.1") is True
    assert mcp_server._host_is_loopback("localhost") is True
    assert mcp_server._host_is_loopback("::1") is True
    assert mcp_server._host_is_loopback("[::1]") is True
    assert mcp_server._host_is_loopback("0.0.0.0") is False
    assert mcp_server._host_is_loopback("example.com") is False
