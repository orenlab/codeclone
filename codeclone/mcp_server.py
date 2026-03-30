# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import ipaddress
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from . import __version__
from .contracts import DOCS_URL
from .mcp_service import (
    DEFAULT_MCP_HISTORY_LIMIT,
    MAX_MCP_HISTORY_LIMIT,
    CodeCloneMCPService,
    MCPAnalysisRequest,
    MCPGateRequest,
    _validated_history_limit,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

_SERVER_INSTRUCTIONS = (
    "CodeClone MCP is a deterministic, baseline-aware, read-only analysis server "
    "for Python repositories. Use analyze_repository first, then query the latest "
    "or a specific run with summary, finding, hotspot, gate, and report-section "
    "tools. This server never updates baselines and never mutates source files."
)
_MCP_INSTALL_HINT = (
    "CodeClone MCP support requires the optional 'mcp' extra. "
    "Install it with: pip install 'codeclone[mcp]'"
)


class MCPDependencyError(RuntimeError):
    """Raised when the optional MCP runtime dependency is unavailable."""


MCPCallable = TypeVar("MCPCallable", bound=Callable[..., object])


def _load_mcp_runtime() -> tuple[type[FastMCP], ToolAnnotations, ToolAnnotations]:
    try:
        from mcp.server.fastmcp import FastMCP as runtime_fastmcp
        from mcp.types import ToolAnnotations as runtime_tool_annotations
    except ImportError as exc:
        raise MCPDependencyError(_MCP_INSTALL_HINT) from exc
    return (
        cast("type[FastMCP]", runtime_fastmcp),
        runtime_tool_annotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        runtime_tool_annotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )


def build_mcp_server(
    *,
    history_limit: int = DEFAULT_MCP_HISTORY_LIMIT,
    host: str = "127.0.0.1",
    port: int = 8000,
    json_response: bool = False,
    stateless_http: bool = False,
    debug: bool = False,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> FastMCP:
    runtime_fastmcp, read_only_tool, session_tool = _load_mcp_runtime()
    service = CodeCloneMCPService(history_limit=_validated_history_limit(history_limit))
    mcp = runtime_fastmcp(
        name="CodeClone",
        instructions=_SERVER_INSTRUCTIONS,
        website_url=DOCS_URL,
        host=host,
        port=port,
        json_response=json_response,
        stateless_http=stateless_http,
        debug=debug,
        log_level=log_level,
        dependencies=(f"codeclone=={__version__}",),
    )

    def tool(*args: Any, **kwargs: Any) -> Callable[[MCPCallable], MCPCallable]:
        return cast(
            "Callable[[MCPCallable], MCPCallable]",
            mcp.tool(*args, **kwargs),
        )

    def resource(
        *args: Any,
        **kwargs: Any,
    ) -> Callable[[MCPCallable], MCPCallable]:
        return cast(
            "Callable[[MCPCallable], MCPCallable]",
            mcp.resource(*args, **kwargs),
        )

    @tool(
        title="Analyze Repository",
        description=(
            "Run a deterministic CodeClone analysis for a repository and register "
            "the result as the latest MCP run. Tip: set cache_policy='off' to "
            "bypass cache and get fully fresh results."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def analyze_repository(
        root: str = ".",
        analysis_mode: str = "full",
        respect_pyproject: bool = True,
        changed_paths: list[str] | None = None,
        git_diff_ref: str | None = None,
        processes: int | None = None,
        min_loc: int | None = None,
        min_stmt: int | None = None,
        block_min_loc: int | None = None,
        block_min_stmt: int | None = None,
        segment_min_loc: int | None = None,
        segment_min_stmt: int | None = None,
        complexity_threshold: int | None = None,
        coupling_threshold: int | None = None,
        cohesion_threshold: int | None = None,
        baseline_path: str | None = None,
        metrics_baseline_path: str | None = None,
        max_baseline_size_mb: int | None = None,
        cache_policy: str = "reuse",
        cache_path: str | None = None,
        max_cache_size_mb: int | None = None,
    ) -> dict[str, object]:
        return service.analyze_repository(
            MCPAnalysisRequest(
                root=root,
                analysis_mode=analysis_mode,  # type: ignore[arg-type]
                respect_pyproject=respect_pyproject,
                changed_paths=tuple(changed_paths or ()),
                git_diff_ref=git_diff_ref,
                processes=processes,
                min_loc=min_loc,
                min_stmt=min_stmt,
                block_min_loc=block_min_loc,
                block_min_stmt=block_min_stmt,
                segment_min_loc=segment_min_loc,
                segment_min_stmt=segment_min_stmt,
                complexity_threshold=complexity_threshold,
                coupling_threshold=coupling_threshold,
                cohesion_threshold=cohesion_threshold,
                baseline_path=baseline_path,
                metrics_baseline_path=metrics_baseline_path,
                max_baseline_size_mb=max_baseline_size_mb,
                cache_policy=cache_policy,  # type: ignore[arg-type]
                cache_path=cache_path,
                max_cache_size_mb=max_cache_size_mb,
            )
        )

    @tool(
        title="Analyze Changed Paths",
        description=(
            "Run a deterministic CodeClone analysis and return a changed-files "
            "projection using explicit paths or a git diff ref. Tip: set "
            "cache_policy='off' to bypass cache and get fully fresh results."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def analyze_changed_paths(
        root: str = ".",
        changed_paths: list[str] | None = None,
        git_diff_ref: str | None = None,
        analysis_mode: str = "full",
        respect_pyproject: bool = True,
        processes: int | None = None,
        min_loc: int | None = None,
        min_stmt: int | None = None,
        block_min_loc: int | None = None,
        block_min_stmt: int | None = None,
        segment_min_loc: int | None = None,
        segment_min_stmt: int | None = None,
        complexity_threshold: int | None = None,
        coupling_threshold: int | None = None,
        cohesion_threshold: int | None = None,
        baseline_path: str | None = None,
        metrics_baseline_path: str | None = None,
        max_baseline_size_mb: int | None = None,
        cache_policy: str = "reuse",
        cache_path: str | None = None,
        max_cache_size_mb: int | None = None,
    ) -> dict[str, object]:
        return service.analyze_changed_paths(
            MCPAnalysisRequest(
                root=root,
                changed_paths=tuple(changed_paths or ()),
                git_diff_ref=git_diff_ref,
                analysis_mode=analysis_mode,  # type: ignore[arg-type]
                respect_pyproject=respect_pyproject,
                processes=processes,
                min_loc=min_loc,
                min_stmt=min_stmt,
                block_min_loc=block_min_loc,
                block_min_stmt=block_min_stmt,
                segment_min_loc=segment_min_loc,
                segment_min_stmt=segment_min_stmt,
                complexity_threshold=complexity_threshold,
                coupling_threshold=coupling_threshold,
                cohesion_threshold=cohesion_threshold,
                baseline_path=baseline_path,
                metrics_baseline_path=metrics_baseline_path,
                max_baseline_size_mb=max_baseline_size_mb,
                cache_policy=cache_policy,  # type: ignore[arg-type]
                cache_path=cache_path,
                max_cache_size_mb=max_cache_size_mb,
            )
        )

    @tool(
        title="Get Run Summary",
        description="Return the stored summary for the latest or specified MCP run.",
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_run_summary(run_id: str | None = None) -> dict[str, object]:
        return service.get_run_summary(run_id)

    @tool(
        title="Get Production Triage",
        description=(
            "Return a production-first triage view over a stored run: health, "
            "effective cache freshness, production hotspots, and production "
            "suggestions, while keeping global source-kind counters visible."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_production_triage(
        run_id: str | None = None,
        max_hotspots: int = 3,
        max_suggestions: int = 3,
    ) -> dict[str, object]:
        return service.get_production_triage(
            run_id=run_id,
            max_hotspots=max_hotspots,
            max_suggestions=max_suggestions,
        )

    @tool(
        title="Evaluate Gates",
        description=(
            "Evaluate CodeClone gate conditions against an existing MCP run without "
            "modifying baselines or exiting the process."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def evaluate_gates(
        run_id: str | None = None,
        fail_on_new: bool = False,
        fail_threshold: int = -1,
        fail_complexity: int = -1,
        fail_coupling: int = -1,
        fail_cohesion: int = -1,
        fail_cycles: bool = False,
        fail_dead_code: bool = False,
        fail_health: int = -1,
        fail_on_new_metrics: bool = False,
    ) -> dict[str, object]:
        return service.evaluate_gates(
            MCPGateRequest(
                run_id=run_id,
                fail_on_new=fail_on_new,
                fail_threshold=fail_threshold,
                fail_complexity=fail_complexity,
                fail_coupling=fail_coupling,
                fail_cohesion=fail_cohesion,
                fail_cycles=fail_cycles,
                fail_dead_code=fail_dead_code,
                fail_health=fail_health,
                fail_on_new_metrics=fail_on_new_metrics,
            )
        )

    @tool(
        title="Get Report Section",
        description=(
            "Return a canonical CodeClone report section for the latest or "
            "specified MCP run. The 'metrics' section returns only the "
            "summary, while 'metrics_detail' returns the full metrics dump."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_report_section(
        run_id: str | None = None,
        section: str = "all",
    ) -> dict[str, object]:
        return service.get_report_section(
            run_id=run_id,
            section=section,  # type: ignore[arg-type]
        )

    @tool(
        title="List Findings",
        description=(
            "List canonical finding groups with deterministic ordering, optional "
            "filters, and pagination."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_findings(
        run_id: str | None = None,
        family: str = "all",
        category: str | None = None,
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: str = "all",
        sort_by: str = "default",
        detail_level: str = "normal",
        changed_paths: list[str] | None = None,
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        offset: int = 0,
        limit: int = 50,
        max_results: int | None = None,
    ) -> dict[str, object]:
        return service.list_findings(
            run_id=run_id,
            family=family,  # type: ignore[arg-type]
            category=category,
            severity=severity,
            source_kind=source_kind,
            novelty=novelty,  # type: ignore[arg-type]
            sort_by=sort_by,  # type: ignore[arg-type]
            detail_level=detail_level,  # type: ignore[arg-type]
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            exclude_reviewed=exclude_reviewed,
            offset=offset,
            limit=limit,
            max_results=max_results,
        )

    @tool(
        title="Get Finding",
        description="Return a single canonical finding group by id.",
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_finding(
        finding_id: str,
        run_id: str | None = None,
    ) -> dict[str, object]:
        return service.get_finding(finding_id=finding_id, run_id=run_id)

    @tool(
        title="Get Remediation",
        description="Return actionable remediation guidance for a single finding.",
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_remediation(
        finding_id: str,
        run_id: str | None = None,
        detail_level: str = "full",
    ) -> dict[str, object]:
        return service.get_remediation(
            finding_id=finding_id,
            run_id=run_id,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="List Hotspots",
        description=(
            "Return one of the derived CodeClone hotlists for the latest or "
            "specified MCP run."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_hotspots(
        kind: str,
        run_id: str | None = None,
        detail_level: str = "normal",
        changed_paths: list[str] | None = None,
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        limit: int = 10,
        max_results: int | None = None,
    ) -> dict[str, object]:
        return service.list_hotspots(
            kind=kind,  # type: ignore[arg-type]
            run_id=run_id,
            detail_level=detail_level,  # type: ignore[arg-type]
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            exclude_reviewed=exclude_reviewed,
            limit=limit,
            max_results=max_results,
        )

    @tool(
        title="Compare Runs",
        description=(
            "Compare two registered CodeClone MCP runs by finding ids and health."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def compare_runs(
        run_id_before: str,
        run_id_after: str | None = None,
        focus: str = "all",
    ) -> dict[str, object]:
        return service.compare_runs(
            run_id_before=run_id_before,
            run_id_after=run_id_after,
            focus=focus,  # type: ignore[arg-type]
        )

    @tool(
        title="Check Complexity",
        description=(
            "Return complexity hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_complexity(
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        min_complexity: int | None = None,
        max_results: int = 10,
        detail_level: str = "normal",
    ) -> dict[str, object]:
        return service.check_complexity(
            run_id=run_id,
            root=root,
            path=path,
            min_complexity=min_complexity,
            max_results=max_results,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="Check Clones",
        description=(
            "Return clone findings from a compatible stored run. "
            "Use analyze_repository first if no compatible run is available."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_clones(
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        clone_type: str | None = None,
        source_kind: str | None = None,
        max_results: int = 10,
        detail_level: str = "normal",
    ) -> dict[str, object]:
        return service.check_clones(
            run_id=run_id,
            root=root,
            path=path,
            clone_type=clone_type,
            source_kind=source_kind,
            max_results=max_results,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="Check Coupling",
        description=(
            "Return coupling hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_coupling(
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        max_results: int = 10,
        detail_level: str = "normal",
    ) -> dict[str, object]:
        return service.check_coupling(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="Check Cohesion",
        description=(
            "Return cohesion hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_cohesion(
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        max_results: int = 10,
        detail_level: str = "normal",
    ) -> dict[str, object]:
        return service.check_cohesion(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="Check Dead Code",
        description=(
            "Return dead-code findings from a compatible stored run. "
            "Use analyze_repository first if no full run is available."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_dead_code(
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        min_severity: str | None = None,
        max_results: int = 10,
        detail_level: str = "normal",
    ) -> dict[str, object]:
        return service.check_dead_code(
            run_id=run_id,
            root=root,
            path=path,
            min_severity=min_severity,
            max_results=max_results,
            detail_level=detail_level,  # type: ignore[arg-type]
        )

    @tool(
        title="Generate PR Summary",
        description="Generate a PR-friendly CodeClone summary for changed files.",
        annotations=read_only_tool,
        structured_output=True,
    )
    def generate_pr_summary(
        run_id: str | None = None,
        changed_paths: list[str] | None = None,
        git_diff_ref: str | None = None,
        format: str = "markdown",
    ) -> dict[str, object]:
        return service.generate_pr_summary(
            run_id=run_id,
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            format=format,  # type: ignore[arg-type]
        )

    @tool(
        title="Mark Finding Reviewed",
        description="Mark a finding as reviewed in the current in-memory MCP session.",
        annotations=session_tool,
        structured_output=True,
    )
    def mark_finding_reviewed(
        finding_id: str,
        run_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, object]:
        return service.mark_finding_reviewed(
            finding_id=finding_id,
            run_id=run_id,
            note=note,
        )

    @tool(
        title="List Reviewed Findings",
        description=(
            "List in-memory reviewed findings for the current or specified run."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_reviewed_findings(run_id: str | None = None) -> dict[str, object]:
        return service.list_reviewed_findings(run_id=run_id)

    @tool(
        title="Clear Session Runs",
        description=(
            "Clear all in-memory MCP analysis runs and ephemeral session state "
            "for this server process."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def clear_session_runs() -> dict[str, object]:
        return service.clear_session_runs()

    @resource(
        "codeclone://latest/summary",
        title="Latest Run Summary",
        description="Canonical JSON summary for the latest CodeClone MCP run.",
        mime_type="application/json",
    )
    def latest_summary_resource() -> str:
        return service.read_resource("codeclone://latest/summary")

    @resource(
        "codeclone://latest/report.json",
        title="Latest Canonical Report",
        description="Canonical JSON report for the latest CodeClone MCP run.",
        mime_type="application/json",
    )
    def latest_report_resource() -> str:
        return service.read_resource("codeclone://latest/report.json")

    @resource(
        "codeclone://latest/health",
        title="Latest Health Snapshot",
        description="Health score and dimensions for the latest CodeClone MCP run.",
        mime_type="application/json",
    )
    def latest_health_resource() -> str:
        return service.read_resource("codeclone://latest/health")

    @resource(
        "codeclone://latest/gates",
        title="Latest Gate Evaluation",
        description="Last gate evaluation result produced by this MCP session.",
        mime_type="application/json",
    )
    def latest_gates_resource() -> str:
        return service.read_resource("codeclone://latest/gates")

    @resource(
        "codeclone://latest/changed",
        title="Latest Changed Findings",
        description=(
            "Changed-files projection for the latest diff-aware CodeClone MCP run."
        ),
        mime_type="application/json",
    )
    def latest_changed_resource() -> str:
        return service.read_resource("codeclone://latest/changed")

    @resource(
        "codeclone://latest/triage",
        title="Latest Production Triage",
        description=("Production-first triage view for the latest CodeClone MCP run."),
        mime_type="application/json",
    )
    def latest_triage_resource() -> str:
        return service.read_resource("codeclone://latest/triage")

    @resource(
        "codeclone://schema",
        title="CodeClone Report Schema",
        description="JSON schema-style descriptor for the canonical CodeClone report.",
        mime_type="application/json",
    )
    def schema_resource() -> str:
        return service.read_resource("codeclone://schema")

    @resource(
        "codeclone://runs/{run_id}/summary",
        title="Run Summary",
        description="Canonical JSON summary for a specific CodeClone MCP run.",
        mime_type="application/json",
    )
    def run_summary_resource(run_id: str) -> str:
        return service.read_resource(f"codeclone://runs/{run_id}/summary")

    @resource(
        "codeclone://runs/{run_id}/report.json",
        title="Run Canonical Report",
        description="Canonical JSON report for a specific CodeClone MCP run.",
        mime_type="application/json",
    )
    def run_report_resource(run_id: str) -> str:
        return service.read_resource(f"codeclone://runs/{run_id}/report.json")

    @resource(
        "codeclone://runs/{run_id}/findings/{finding_id}",
        title="Run Finding",
        description="Canonical JSON finding group for a specific CodeClone MCP run.",
        mime_type="application/json",
    )
    def run_finding_resource(run_id: str, finding_id: str) -> str:
        return service.read_resource(f"codeclone://runs/{run_id}/findings/{finding_id}")

    return mcp


def _history_limit_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"history limit must be an integer between 1 and {MAX_MCP_HISTORY_LIMIT}."
        ) from exc
    try:
        return _validated_history_limit(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeclone-mcp",
        description=(
            "CodeClone MCP server for deterministic, baseline-aware, read-only "
            "analysis of Python repositories."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to run. Defaults to stdio.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when using streamable-http.",
    )
    parser.add_argument(
        "--allow-remote",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Allow binding streamable-http to a non-loopback host. "
            "Disabled by default because CodeClone MCP has no built-in authentication."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind when using streamable-http.",
    )
    parser.add_argument(
        "--history-limit",
        type=_history_limit_arg,
        default=DEFAULT_MCP_HISTORY_LIMIT,
        help=(
            "Maximum number of in-memory analysis runs retained by the server "
            f"(1-{MAX_MCP_HISTORY_LIMIT}, default: {DEFAULT_MCP_HISTORY_LIMIT})."
        ),
    )
    parser.add_argument(
        "--json-response",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use JSON responses for streamable-http transport.",
    )
    parser.add_argument(
        "--stateless-http",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use stateless Streamable HTTP mode when transport is streamable-http.",
    )
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable FastMCP debug mode.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="FastMCP server log level.",
    )
    return parser


def _host_is_loopback(host: str) -> bool:
    cleaned = host.strip().strip("[]")
    if not cleaned:
        return False
    if cleaned.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def main() -> None:
    args = build_parser().parse_args()
    if (
        args.transport == "streamable-http"
        and not args.allow_remote
        and not _host_is_loopback(args.host)
    ):
        print(
            (
                "Refusing to bind CodeClone MCP streamable-http to non-loopback "
                f"host '{args.host}' without --allow-remote. "
                "The server has no built-in authentication."
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        server = build_mcp_server(
            history_limit=args.history_limit,
            host=args.host,
            port=args.port,
            json_response=args.json_response,
            stateless_http=args.stateless_http,
            debug=args.debug,
            log_level=args.log_level,
        )
    except MCPDependencyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    try:
        server.run(transport=args.transport)
    except KeyboardInterrupt:
        return


__all__ = [
    "MCPDependencyError",
    "build_mcp_server",
    "build_parser",
    "main",
]
