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

import codeclone.surfaces.mcp.server as mcp_server
from codeclone import __version__ as CODECLONE_VERSION
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.surfaces.mcp.server import MCPDependencyError, build_mcp_server
from tests._mcp_fixtures import write_quality_fixture as _write_shared_quality_fixture


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
    _write_shared_quality_fixture(
        root,
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
    )


def test_mcp_server_exposes_expected_read_only_tools() -> None:
    _require_mcp_runtime()
    server = build_mcp_server(history_limit=4)
    init_options = server._mcp_server.create_initialization_options()

    assert "prefer get_run_summary or get_production_triage" in str(server.instructions)
    assert "Use list_hotspots or focused check_* tools" in str(server.instructions)
    assert "prefer generate_pr_summary(format='markdown')" in str(server.instructions)
    assert "Use help(topic=...)" in str(server.instructions)
    assert "default or pyproject-resolved thresholds for the first pass" in str(
        server.instructions
    )

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "analyze_repository",
        "analyze_changed_paths",
        "clear_session_runs",
        "help",
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
                "analyze_repository",
                "analyze_changed_paths",
                "check_complexity",
                "check_clones",
                "check_coupling",
                "check_cohesion",
                "check_dead_code",
                "get_run_summary",
                "get_production_triage",
                "evaluate_gates",
                "help",
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
        assert tool.annotations.destructiveHint is (
            name in {"mark_finding_reviewed", "clear_session_runs"}
        )
        assert tool.annotations.idempotentHint is True
    assert "cache_policy='off'" in str(tools["analyze_repository"].description)
    assert "cache_policy='off'" in str(tools["analyze_changed_paths"].description)
    assert "absolute repository root" in str(tools["analyze_repository"].description)
    assert "absolute repository root" in str(tools["analyze_changed_paths"].description)
    assert "get_run_summary or get_production_triage" in str(
        tools["analyze_repository"].description
    )
    assert "conservative first pass" in str(tools["analyze_repository"].description)
    assert "get_report_section(section='changed')" in str(
        tools["analyze_changed_paths"].description
    )
    assert "conservative profile first" in str(
        tools["analyze_changed_paths"].description
    )
    assert "Use analyze_repository first" in str(tools["check_complexity"].description)
    assert "Use analyze_repository first" in str(tools["check_clones"].description)
    assert "default first-pass review" in str(
        tools["get_production_triage"].description
    )
    assert "bounded guidance, not a full manual" in str(tools["help"].description)
    assert "workflow, analysis_profile, suppressions, baseline" in str(
        tools["help"].description
    )
    assert init_options.server_version == CODECLONE_VERSION
    assert "Prefer list_hotspots or focused check_* tools" in str(
        tools["list_findings"].description
    )
    assert "Use this after list_hotspots" in str(tools["get_finding"].description)
    assert "Prefer this for first-pass triage" in str(
        tools["list_hotspots"].description
    )
    assert "Prefer format='markdown'" in str(tools["generate_pr_summary"].description)
    assert "Prefer specific sections instead of 'all'" in str(
        tools["get_report_section"].description
    )
    analyze_repository_schema = cast(
        "dict[str, object]",
        tools["analyze_repository"].inputSchema,
    )
    analyze_changed_schema = cast(
        "dict[str, object]",
        tools["analyze_changed_paths"].inputSchema,
    )
    assert "root" in cast("list[str]", analyze_repository_schema["required"])
    assert "root" in cast("list[str]", analyze_changed_schema["required"])
    assert "default" not in cast(
        "dict[str, object]",
        cast("dict[str, object]", analyze_repository_schema["properties"])["root"],
    )
    assert "default" not in cast(
        "dict[str, object]",
        cast("dict[str, object]", analyze_changed_schema["properties"])["root"],
    )


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
    assert "inventory" not in changed_summary
    assert cast(int, changed_summary["changed_files"]) == 1

    latest = _structured_tool_result(
        asyncio.run(server.call_tool("get_run_summary", {}))
    )
    assert latest["run_id"] == run_id
    assert set(cast("dict[str, object]", latest["inventory"])) == {
        "files",
        "lines",
        "functions",
        "classes",
    }

    help_payload = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "help",
                {"topic": "changed_scope", "detail": "normal"},
            )
        )
    )
    assert help_payload["topic"] == "changed_scope"
    assert help_payload["detail"] == "normal"
    assert "warnings" in help_payload
    assert "recommended_tools" in help_payload

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
    summary_finding = cast("list[dict[str, object]]", findings_result["items"])[0]
    assert "priority_factors" not in summary_finding
    assert all(
        isinstance(location, str)
        for location in cast("list[object]", summary_finding["locations"])
    )

    latest_summary_resource = list(
        asyncio.run(server.read_resource("codeclone://latest/summary"))
    )
    assert latest_summary_resource
    latest_summary_text = latest_summary_resource[0].content
    latest_summary = json.loads(latest_summary_text)
    assert latest_summary["run_id"] == run_id
    assert set(cast("dict[str, object]", latest_summary["inventory"])) == {
        "files",
        "lines",
        "functions",
        "classes",
    }

    production_triage = _structured_tool_result(
        asyncio.run(server.call_tool("get_production_triage", {}))
    )
    assert production_triage["run_id"] == run_id
    assert _mapping_child(production_triage, "cache")["freshness"]

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
    assert latest_changed_payload["changed_paths"] == ["pkg/dup.py"]
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
    assert "_hint" in metrics_detail_section
    metrics_detail_page = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "get_report_section",
                {"section": "metrics_detail", "family": "complexity", "limit": 5},
            )
        )
    )
    overloaded_modules_page = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "get_report_section",
                {
                    "section": "metrics_detail",
                    "family": "overloaded_modules",
                    "limit": 5,
                },
            )
        )
    )
    overloaded_modules_alias_page = _structured_tool_result(
        asyncio.run(
            server.call_tool(
                "get_report_section",
                {"section": "metrics_detail", "family": "god_modules", "limit": 5},
            )
        )
    )
    assert cast("list[dict[str, object]]", metrics_detail_page["items"])
    assert overloaded_modules_page["family"] == "overloaded_modules"
    assert overloaded_modules_alias_page["family"] == "overloaded_modules"
    assert overloaded_modules_alias_page["items"] == overloaded_modules_page["items"]
    report_metrics = cast("dict[str, object]", report_payload["metrics"])
    report_families = cast("dict[str, object]", report_metrics["families"])
    report_overloaded_modules = cast(
        "dict[str, object]", report_families["overloaded_modules"]
    )
    report_overloaded_module_items = cast(
        "list[dict[str, object]]",
        report_overloaded_modules["items"],
    )
    assert (
        cast("list[dict[str, object]]", overloaded_modules_page["items"])[0]["path"]
        == report_overloaded_module_items[0]["relative_path"]
    )
    changed_section = _structured_tool_result(
        asyncio.run(server.call_tool("get_report_section", {"section": "changed"}))
    )
    assert changed_section["changed_paths"] == ["pkg/dup.py"]

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
    assert cast(int, clones["total"]) >= 1
    assert coupling["check"] == "coupling"
    assert cohesion["check"] == "cohesion"
    assert dead_code["check"] == "dead_code"
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
