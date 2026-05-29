# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import ipaddress
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, TypeVar

from ... import __version__
from ...contracts import DEFAULT_COVERAGE_MIN, DOCS_URL
from ._tool_param_docs import (
    AfterRunIdParam,
    AnalysisModeParam,
    ApiSurfaceParam,
    AutoClearParam,
    BeforeRunIdParam,
    BlastDepthParam,
    BlastRadiusDepthParam,
    CachePolicyParam,
    CategoryParam,
    ChangedFilesParam,
    ChangedPathsParam,
    CloneTypeParam,
    CompareFocusParam,
    CoverageMinParam,
    CoverageXmlParam,
    CreateReceiptParam,
    DetailLevelParam,
    DiffRefParam,
    ExcludeReviewedParam,
    ExpectedEffectsParam,
    FamilyParam,
    FilesParam,
    FindingFamilyParam,
    FindingIdParam,
    GateBoolParam,
    GateIntParam,
    GitDiffRefParam,
    HelpDetailParam,
    HelpTopicParam,
    HotspotKindParam,
    IncludeBlastRadiusParam,
    IncludeParam,
    IncludePatchContractParam,
    IntentIdParam,
    IntentTextParam,
    LeaseSecondsParam,
    LimitParam,
    ManageActionParam,
    MaxHotspotsParam,
    MaxResultsParam,
    MaxSizeMbParam,
    MaxSuggestionsParam,
    MinComplexityParam,
    MinSeverityParam,
    NoveltyParam,
    OffsetParam,
    OnConflictParam,
    OptionalIntentIdParam,
    OptionalIntentTextParam,
    OptionalPathParam,
    OptionalRootParam,
    OptionalScopeParam,
    PatchModeParam,
    PathFilterParam,
    PrFormatParam,
    ProcessesParam,
    ReceiptFormatParam,
    ReportSectionParam,
    RequireCitationsParam,
    RespectPyprojectParam,
    ReviewNoteParam,
    ReviewTextParam,
    RootParam,
    RunIdParam,
    RunIdRequiredParam,
    ScopeParam,
    SeverityParam,
    SortByParam,
    SourceKindParam,
    StrictnessParam,
    ThresholdIntParam,
    TtlSecondsParam,
)
from .service import CodeCloneMCPService
from .session import (
    DEFAULT_MCP_HISTORY_LIMIT,
    MAX_MCP_HISTORY_LIMIT,
    AnalysisMode,
    CachePolicy,
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPServiceContractError,
    _validated_history_limit,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

_SERVER_INSTRUCTIONS = (
    "CodeClone MCP is a deterministic, baseline-aware, read-only analysis server "
    "for Python repositories. Use analyze_repository first for full runs or "
    "analyze_changed_paths for PR-style review, then prefer get_run_summary or "
    "get_production_triage for the first pass. Use list_hotspots or focused "
    "check_* tools before broader list_findings calls, then drill into one "
    "finding with get_finding or get_remediation. Use "
    "help(topic=...) when workflow or contract semantics are unclear. Use "
    "default or pyproject-resolved thresholds for the first pass, and lower "
    "them only for an explicit higher-sensitivity follow-up when needed. Use "
    "get_report_section(section='metrics_detail', family=..., limit=...) for "
    "bounded metrics drill-down, and prefer generate_pr_summary(format='markdown') "
    "unless machine JSON is required. Coverage join accepts external Cobertura "
    "XML as a current-run signal and does not become baseline truth. Pass an "
    "absolute repository root to analysis tools. For file edits, prefer "
    "start_controlled_change and finish_controlled_change for the complete "
    "edit cycle. Use manage_change_intent for queue/promote/recover "
    "operations. Atomic tools (get_blast_radius, check_patch_contract, "
    "validate_review_claims, create_review_receipt) remain available for "
    "advanced inspection and diagnostic use. "
    "If concurrent intents overlap, narrow scope or coordinate. This server never "
    "updates baselines and never mutates source files, analysis cache, or reports; "
    "it may write ephemeral workspace coordination state under "
    ".cache/codeclone/intents/."
)
_MCP_INSTALL_HINT = (
    "CodeClone MCP support requires the optional 'mcp' extra. "
    "Install it with: pip install 'codeclone[mcp]'"
)
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000
DEFAULT_MCP_JSON_RESPONSE = True
DEFAULT_MCP_STATELESS_HTTP = True
DEFAULT_MCP_DEBUG = False
DEFAULT_MCP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class MCPDependencyError(RuntimeError):
    """Raised when the optional MCP runtime dependency is unavailable."""


MCPCallable = TypeVar("MCPCallable", bound=Callable[..., object])


def _load_mcp_runtime() -> tuple[
    type[FastMCP],
    ToolAnnotations,
    ToolAnnotations,
    ToolAnnotations,
]:
    try:
        from mcp.server.fastmcp import FastMCP as imported_fastmcp
        from mcp.types import ToolAnnotations as runtime_tool_annotations
    except ImportError as exc:
        raise MCPDependencyError(_MCP_INSTALL_HINT) from exc
    runtime_fastmcp: type[FastMCP] = imported_fastmcp
    return (
        runtime_fastmcp,
        runtime_tool_annotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        runtime_tool_annotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        runtime_tool_annotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )


def _validated_analysis_mode(value: str) -> AnalysisMode:
    if value == "full":
        return "full"
    if value == "clones_only":
        return "clones_only"
    raise MCPServiceContractError(
        f"Invalid value for analysis_mode: {value!r}. "
        "Expected one of: clones_only, full."
    )


def _validated_cache_policy(value: str) -> CachePolicy:
    if value == "reuse":
        return "reuse"
    if value == "off":
        return "off"
    if value == "refresh":
        raise MCPServiceContractError(
            "cache_policy='refresh' is CLI-only. MCP accepts: reuse, off."
        )
    raise MCPServiceContractError(
        f"Invalid value for cache_policy: {value!r}. Expected one of: off, reuse."
    )


def build_mcp_server(
    *,
    history_limit: int = DEFAULT_MCP_HISTORY_LIMIT,
    host: str = DEFAULT_MCP_HOST,
    port: int = DEFAULT_MCP_PORT,
    json_response: bool = DEFAULT_MCP_JSON_RESPONSE,
    stateless_http: bool = DEFAULT_MCP_STATELESS_HTTP,
    debug: bool = DEFAULT_MCP_DEBUG,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        DEFAULT_MCP_LOG_LEVEL
    ),
) -> FastMCP:
    """Build and register the local read-only CodeClone FastMCP server."""

    runtime_fastmcp, read_only_tool, analysis_tool, session_tool = _load_mcp_runtime()
    service = CodeCloneMCPService(history_limit=_validated_history_limit(history_limit))

    @asynccontextmanager
    async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, object]]:
        yield {}
        service.shutdown_cleanup()

    mcp = runtime_fastmcp(
        name="CodeClone",
        instructions=_SERVER_INSTRUCTIONS,
        lifespan=_lifespan,
        website_url=DOCS_URL,
        host=host,
        port=port,
        json_response=json_response,
        stateless_http=stateless_http,
        debug=debug,
        log_level=log_level,
        dependencies=(f"codeclone=={__version__}",),
    )
    # FastMCP otherwise reports the `mcp` package version in initialize/serverInfo.
    mcp._mcp_server.version = __version__
    # Inject FastMCP reference so the service can lazily resolve the MCP
    # clientInfo (name/version) for workspace intent agent_label fields.
    service._fastmcp = mcp

    def tool(*args: object, **kwargs: object) -> Callable[[MCPCallable], MCPCallable]:
        decorator = mcp.tool(*args, **kwargs)  # type: ignore[arg-type]

        def register(func: MCPCallable) -> MCPCallable:
            decorator(func)
            return func

        return register

    def resource(
        *args: object,
        **kwargs: object,
    ) -> Callable[[MCPCallable], MCPCallable]:
        decorator = mcp.resource(*args, **kwargs)  # type: ignore[arg-type]

        def register(func: MCPCallable) -> MCPCallable:
            decorator(func)
            return func

        return register

    @tool(
        title="Analyze Repository",
        description=(
            "Run a deterministic CodeClone analysis and register it as the "
            "latest MCP run. Pass an absolute repository root; relative roots "
            "like '.' are rejected in MCP. MCP cache_policy accepts reuse or "
            "off only. Start with get_production_triage."
        ),
        annotations=analysis_tool,
        structured_output=True,
    )
    def analyze_repository(
        root: RootParam,
        analysis_mode: AnalysisModeParam = "full",
        respect_pyproject: RespectPyprojectParam = True,
        changed_paths: ChangedPathsParam = None,
        git_diff_ref: GitDiffRefParam = None,
        processes: ProcessesParam = None,
        min_loc: ThresholdIntParam = None,
        min_stmt: ThresholdIntParam = None,
        block_min_loc: ThresholdIntParam = None,
        block_min_stmt: ThresholdIntParam = None,
        segment_min_loc: ThresholdIntParam = None,
        segment_min_stmt: ThresholdIntParam = None,
        api_surface: ApiSurfaceParam = None,
        coverage_xml: CoverageXmlParam = None,
        coverage_min: CoverageMinParam = None,
        complexity_threshold: ThresholdIntParam = None,
        coupling_threshold: ThresholdIntParam = None,
        cohesion_threshold: ThresholdIntParam = None,
        baseline_path: OptionalPathParam = None,
        metrics_baseline_path: OptionalPathParam = None,
        max_baseline_size_mb: MaxSizeMbParam = None,
        cache_policy: CachePolicyParam = "reuse",
        cache_path: OptionalPathParam = None,
        max_cache_size_mb: MaxSizeMbParam = None,
    ) -> dict[str, object]:
        return service.analyze_repository(
            MCPAnalysisRequest(
                root=root,
                analysis_mode=_validated_analysis_mode(analysis_mode),
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
                api_surface=api_surface,
                coverage_xml=coverage_xml,
                coverage_min=coverage_min,
                complexity_threshold=complexity_threshold,
                coupling_threshold=coupling_threshold,
                cohesion_threshold=cohesion_threshold,
                baseline_path=baseline_path,
                metrics_baseline_path=metrics_baseline_path,
                max_baseline_size_mb=max_baseline_size_mb,
                cache_policy=_validated_cache_policy(cache_policy),
                cache_path=cache_path,
                max_cache_size_mb=max_cache_size_mb,
            )
        )

    @tool(
        title="Analyze Changed Paths",
        description=(
            "Run changed-files analysis from explicit paths or git diff ref. "
            "Absolute root required. MCP cache_policy: reuse or off. "
            "Response includes next_tool hint."
        ),
        annotations=analysis_tool,
        structured_output=True,
    )
    def analyze_changed_paths(
        root: RootParam,
        changed_paths: ChangedPathsParam = None,
        git_diff_ref: GitDiffRefParam = None,
        analysis_mode: AnalysisModeParam = "full",
        respect_pyproject: RespectPyprojectParam = True,
        processes: ProcessesParam = None,
        min_loc: ThresholdIntParam = None,
        min_stmt: ThresholdIntParam = None,
        block_min_loc: ThresholdIntParam = None,
        block_min_stmt: ThresholdIntParam = None,
        segment_min_loc: ThresholdIntParam = None,
        segment_min_stmt: ThresholdIntParam = None,
        api_surface: ApiSurfaceParam = None,
        coverage_xml: CoverageXmlParam = None,
        coverage_min: CoverageMinParam = None,
        complexity_threshold: ThresholdIntParam = None,
        coupling_threshold: ThresholdIntParam = None,
        cohesion_threshold: ThresholdIntParam = None,
        baseline_path: OptionalPathParam = None,
        metrics_baseline_path: OptionalPathParam = None,
        max_baseline_size_mb: MaxSizeMbParam = None,
        cache_policy: CachePolicyParam = "reuse",
        cache_path: OptionalPathParam = None,
        max_cache_size_mb: MaxSizeMbParam = None,
    ) -> dict[str, object]:
        return service.analyze_changed_paths(
            MCPAnalysisRequest(
                root=root,
                changed_paths=tuple(changed_paths or ()),
                git_diff_ref=git_diff_ref,
                analysis_mode=_validated_analysis_mode(analysis_mode),
                respect_pyproject=respect_pyproject,
                processes=processes,
                min_loc=min_loc,
                min_stmt=min_stmt,
                block_min_loc=block_min_loc,
                block_min_stmt=block_min_stmt,
                segment_min_loc=segment_min_loc,
                segment_min_stmt=segment_min_stmt,
                api_surface=api_surface,
                coverage_xml=coverage_xml,
                coverage_min=coverage_min,
                complexity_threshold=complexity_threshold,
                coupling_threshold=coupling_threshold,
                cohesion_threshold=cohesion_threshold,
                baseline_path=baseline_path,
                metrics_baseline_path=metrics_baseline_path,
                max_baseline_size_mb=max_baseline_size_mb,
                cache_policy=_validated_cache_policy(cache_policy),
                cache_path=cache_path,
                max_cache_size_mb=max_cache_size_mb,
            )
        )

    @tool(
        title="Get Run Summary",
        description=(
            "Compact run snapshot for latest or specified run. run_id accepts "
            "8-char short id or full digest."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_run_summary(run_id: RunIdParam = None) -> dict[str, object]:
        return service.get_run_summary(run_id)

    @tool(
        title="Get Production Triage",
        description=(
            "Return a production-first triage view over a stored run: health, "
            "cache freshness, production hotspots, and production suggestions, "
            "while keeping global source-kind counters visible. Use this as the "
            "default first-pass review on noisy repositories."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_production_triage(
        run_id: RunIdParam = None,
        max_hotspots: MaxHotspotsParam = 3,
        max_suggestions: MaxSuggestionsParam = 3,
    ) -> dict[str, object]:
        return service.get_production_triage(
            run_id=run_id,
            max_hotspots=max_hotspots,
            max_suggestions=max_suggestions,
        )

    @tool(
        title="Get Blast Radius",
        description=(
            "Return the deterministic structural risk boundary for changing "
            "the given files. Shows direct dependents, clone cohort members, "
            "coverage gaps, actionable do-not-touch paths, and review-only "
            "context. Derived from the canonical report; no new analysis is "
            "performed."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_blast_radius(
        files: FilesParam,
        run_id: RunIdParam = None,
        depth: BlastDepthParam = "direct",
        include: IncludeParam = None,
    ) -> dict[str, object]:
        return service.get_blast_radius(
            files=files,
            run_id=run_id,
            depth=depth,
            include=include,
        )

    @tool(
        title="Check Patch Contract",
        description=(
            "Pre-edit budget query (mode='budget') or post-edit structural "
            "verification (mode='verify'). Composes stored runs, gate "
            "evaluation, run comparison, and session-local change intent "
            "without running analysis or mutating repository state."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_patch_contract(
        mode: PatchModeParam,
        run_id: RunIdParam = None,
        before_run_id: BeforeRunIdParam = None,
        after_run_id: AfterRunIdParam = None,
        intent_id: OptionalIntentIdParam = None,
        strictness: StrictnessParam = "ci",
        diff_ref: DiffRefParam = None,
        changed_files: ChangedFilesParam = None,
    ) -> dict[str, object]:
        return service.check_patch_contract(
            mode=mode,
            run_id=run_id,
            before_run_id=before_run_id,
            after_run_id=after_run_id,
            intent_id=intent_id,
            strictness=strictness,
            diff_ref=diff_ref,
            changed_files=changed_files,
        )

    @tool(
        title="Create Review Receipt",
        description=(
            "Generate a deterministic, auditable review receipt from stored "
            "MCP state: report provenance, intent scope, blast radius, "
            "reviewed findings, patch contract status, human decision points, "
            "and claims-not-made. Output markdown or JSON without mutating "
            "repository state."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def create_review_receipt(
        run_id: RunIdParam = None,
        intent_id: OptionalIntentIdParam = None,
        format: ReceiptFormatParam = "markdown",
        include_blast_radius: IncludeBlastRadiusParam = True,
        include_patch_contract: IncludePatchContractParam = True,
    ) -> dict[str, object]:
        return service.create_review_receipt(
            run_id=run_id,
            intent_id=intent_id,
            format=format,
            include_blast_radius=include_blast_radius,
            include_patch_contract=include_patch_contract,
        )

    @tool(
        title="Validate Review Claims",
        description=(
            "Validate cited review text against canonical report semantics. "
            "Detects deterministic mischaracterizations: Security Surfaces "
            "called vulnerabilities, report-only signals called CI failures, "
            "known baseline debt called new regressions, dead code claimed "
            "where runtime reachability evidence exists, and fixes claimed "
            "without post-patch verification. Structural citation matching; "
            "not NLP."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def validate_review_claims(
        text: ReviewTextParam,
        run_id: RunIdParam = None,
        require_citations: RequireCitationsParam = True,
    ) -> dict[str, object]:
        return service.validate_review_claims(
            text=text,
            run_id=run_id,
            require_citations=require_citations,
        )

    @tool(
        title="Help",
        description=(
            "Bounded workflow/contract guidance with doc links. compact "
            "includes anti_patterns; normal adds warnings. Topics include "
            "workflow, change_control, trust_boundaries."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def help(
        topic: HelpTopicParam,
        detail: HelpDetailParam = "compact",
    ) -> dict[str, object]:
        return service.get_help(
            topic=topic,
            detail=detail,
        )

    @tool(
        title="Evaluate Gates",
        description=(
            "Evaluate CodeClone gate conditions against an existing MCP run without "
            "modifying baselines or exiting the process."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def evaluate_gates(
        run_id: RunIdParam = None,
        fail_on_new: GateBoolParam = False,
        fail_threshold: GateIntParam = -1,
        fail_complexity: GateIntParam = -1,
        fail_coupling: GateIntParam = -1,
        fail_cohesion: GateIntParam = -1,
        fail_cycles: GateBoolParam = False,
        fail_dead_code: GateBoolParam = False,
        fail_health: GateIntParam = -1,
        fail_on_new_metrics: GateBoolParam = False,
        fail_on_typing_regression: GateBoolParam = False,
        fail_on_docstring_regression: GateBoolParam = False,
        fail_on_api_break: GateBoolParam = False,
        fail_on_untested_hotspots: GateBoolParam = False,
        min_typing_coverage: GateIntParam = -1,
        min_docstring_coverage: GateIntParam = -1,
        coverage_min: GateIntParam = DEFAULT_COVERAGE_MIN,
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
                fail_on_typing_regression=fail_on_typing_regression,
                fail_on_docstring_regression=fail_on_docstring_regression,
                fail_on_api_break=fail_on_api_break,
                fail_on_untested_hotspots=fail_on_untested_hotspots,
                min_typing_coverage=min_typing_coverage,
                min_docstring_coverage=min_docstring_coverage,
                coverage_min=coverage_min,
            )
        )

    @tool(
        title="Get Report Section",
        description=(
            "Return one canonical report section. Prefer metrics, metrics_detail, "
            "changed, findings over all unless necessary."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_report_section(
        run_id: RunIdParam = None,
        section: ReportSectionParam = "all",
        family: FamilyParam = None,
        path: PathFilterParam = None,
        offset: OffsetParam = 0,
        limit: LimitParam = 50,
    ) -> dict[str, object]:
        return service.get_report_section(
            run_id=run_id,
            section=section,
            family=family,
            path=path,
            offset=offset,
            limit=limit,
        )

    @tool(
        title="List Findings",
        description=(
            "List canonical finding groups with deterministic ordering, optional "
            "filters, pagination, and compact summary cards by default. Prefer "
            "list_hotspots or focused check_* tools for first-pass triage; use "
            "this when you need a broader filtered list."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_findings(
        run_id: RunIdParam = None,
        family: FindingFamilyParam = "all",
        category: CategoryParam = None,
        severity: SeverityParam = None,
        source_kind: SourceKindParam = None,
        novelty: NoveltyParam = "all",
        sort_by: SortByParam = "default",
        detail_level: DetailLevelParam = "summary",
        changed_paths: ChangedPathsParam = None,
        git_diff_ref: GitDiffRefParam = None,
        exclude_reviewed: ExcludeReviewedParam = False,
        offset: OffsetParam = 0,
        limit: LimitParam = 50,
        max_results: MaxResultsParam = None,
    ) -> dict[str, object]:
        return service.list_findings(
            run_id=run_id,
            family=family,
            category=category,
            severity=severity,
            source_kind=source_kind,
            novelty=novelty,
            sort_by=sort_by,
            detail_level=detail_level,
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            exclude_reviewed=exclude_reviewed,
            offset=offset,
            limit=limit,
            max_results=max_results,
        )

    @tool(
        title="Get Finding",
        description=(
            "Return a single canonical finding group by short or full id. "
            "Normal detail is the default. Use this after list_hotspots, "
            "list_findings, or check_* instead of requesting larger lists at "
            "higher detail."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_finding(
        finding_id: FindingIdParam,
        run_id: RunIdParam = None,
        detail_level: DetailLevelParam = "normal",
    ) -> dict[str, object]:
        return service.get_finding(
            finding_id=finding_id,
            run_id=run_id,
            detail_level=detail_level,
        )

    @tool(
        title="Get Remediation",
        description=(
            "Return actionable remediation guidance for a single finding. "
            "Normal detail is the default. Use this when you need the fix packet "
            "for one finding without pulling larger detail lists."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_remediation(
        finding_id: FindingIdParam,
        run_id: RunIdParam = None,
        detail_level: DetailLevelParam = "normal",
    ) -> dict[str, object]:
        return service.get_remediation(
            finding_id=finding_id,
            run_id=run_id,
            detail_level=detail_level,
        )

    @tool(
        title="List Hotspots",
        description=(
            "Return one of the derived CodeClone hotlists for the latest or "
            "specified MCP run, using compact summary cards by default. Prefer "
            "this for first-pass triage before broader list_findings calls."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_hotspots(
        kind: HotspotKindParam,
        run_id: RunIdParam = None,
        detail_level: DetailLevelParam = "summary",
        changed_paths: ChangedPathsParam = None,
        git_diff_ref: GitDiffRefParam = None,
        exclude_reviewed: ExcludeReviewedParam = False,
        limit: LimitParam = 10,
        max_results: MaxResultsParam = None,
    ) -> dict[str, object]:
        return service.list_hotspots(
            kind=kind,
            run_id=run_id,
            detail_level=detail_level,
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            exclude_reviewed=exclude_reviewed,
            limit=limit,
            max_results=max_results,
        )

    @tool(
        title="Compare Runs",
        description=(
            "Compare two runs by finding ids. run_id accepts short or full ids. "
            "Returns incomparable when roots or settings differ."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def compare_runs(
        run_id_before: RunIdRequiredParam,
        run_id_after: RunIdParam = None,
        focus: CompareFocusParam = "all",
    ) -> dict[str, object]:
        return service.compare_runs(
            run_id_before=run_id_before,
            run_id_after=run_id_after,
            focus=focus,
        )

    @tool(
        title="Check Complexity",
        description=(
            "Return complexity hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available. When "
            "filtering by root without run_id, pass an absolute root. Prefer "
            "this narrower tool instead of list_findings when you only need "
            "complexity hotspots."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_complexity(
        run_id: RunIdParam = None,
        root: OptionalRootParam = None,
        path: PathFilterParam = None,
        min_complexity: MinComplexityParam = None,
        max_results: LimitParam = 10,
        detail_level: DetailLevelParam = "summary",
    ) -> dict[str, object]:
        return service.check_complexity(
            run_id=run_id,
            root=root,
            path=path,
            min_complexity=min_complexity,
            max_results=max_results,
            detail_level=detail_level,
        )

    @tool(
        title="Check Clones",
        description=(
            "Return clone findings from a compatible stored run. "
            "Use analyze_repository first if no compatible run is available. "
            "When filtering by root without run_id, pass an absolute root. "
            "Prefer this narrower tool instead of list_findings when you only "
            "need clone findings."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_clones(
        run_id: RunIdParam = None,
        root: OptionalRootParam = None,
        path: PathFilterParam = None,
        clone_type: CloneTypeParam = None,
        source_kind: SourceKindParam = None,
        max_results: LimitParam = 10,
        detail_level: DetailLevelParam = "summary",
    ) -> dict[str, object]:
        return service.check_clones(
            run_id=run_id,
            root=root,
            path=path,
            clone_type=clone_type,
            source_kind=source_kind,
            max_results=max_results,
            detail_level=detail_level,
        )

    @tool(
        title="Check Coupling",
        description=(
            "Return coupling hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available. When "
            "filtering by root without run_id, pass an absolute root. Prefer "
            "this narrower tool instead of list_findings when you only need "
            "coupling hotspots."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_coupling(
        run_id: RunIdParam = None,
        root: OptionalRootParam = None,
        path: PathFilterParam = None,
        max_results: LimitParam = 10,
        detail_level: DetailLevelParam = "summary",
    ) -> dict[str, object]:
        return service.check_coupling(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,
        )

    @tool(
        title="Check Cohesion",
        description=(
            "Return cohesion hotspots from a compatible stored run. "
            "Use analyze_repository first if no full run is available. When "
            "filtering by root without run_id, pass an absolute root. Prefer "
            "this narrower tool instead of list_findings when you only need "
            "cohesion hotspots."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_cohesion(
        run_id: RunIdParam = None,
        root: OptionalRootParam = None,
        path: PathFilterParam = None,
        max_results: LimitParam = 10,
        detail_level: DetailLevelParam = "summary",
    ) -> dict[str, object]:
        return service.check_cohesion(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,
        )

    @tool(
        title="Check Dead Code",
        description=(
            "Return dead-code findings from a compatible stored run. "
            "Use analyze_repository first if no full run is available. When "
            "filtering by root without run_id, pass an absolute root. Prefer "
            "this narrower tool instead of list_findings when you only need "
            "dead-code findings."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def check_dead_code(
        run_id: RunIdParam = None,
        root: OptionalRootParam = None,
        path: PathFilterParam = None,
        min_severity: MinSeverityParam = None,
        max_results: LimitParam = 10,
        detail_level: DetailLevelParam = "normal",
    ) -> dict[str, object]:
        return service.check_dead_code(
            run_id=run_id,
            root=root,
            path=path,
            min_severity=min_severity,
            max_results=max_results,
            detail_level=detail_level,
        )

    @tool(
        title="Generate PR Summary",
        description=(
            "Generate a PR-friendly CodeClone summary for changed files. Prefer "
            "format='markdown' for compact LLM-facing output; use 'json' only "
            "for machine post-processing."
        ),
        annotations=read_only_tool,
        structured_output=True,
    )
    def generate_pr_summary(
        run_id: RunIdParam = None,
        changed_paths: ChangedPathsParam = None,
        git_diff_ref: GitDiffRefParam = None,
        format: PrFormatParam = "markdown",
    ) -> dict[str, object]:
        return service.generate_pr_summary(
            run_id=run_id,
            changed_paths=tuple(changed_paths or ()),
            git_diff_ref=git_diff_ref,
            format=format,
        )

    @tool(
        title="Mark Finding Reviewed",
        description=(
            "Mark finding reviewed in this MCP session only; cleared on "
            "process restart or clear_session_runs."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def mark_finding_reviewed(
        finding_id: FindingIdParam,
        run_id: RunIdParam = None,
        note: ReviewNoteParam = None,
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
    def list_reviewed_findings(run_id: RunIdParam = None) -> dict[str, object]:
        return service.list_reviewed_findings(run_id=run_id)

    @tool(
        title="Start Controlled Change",
        description=(
            "Pre-edit workflow: check workspace for concurrent intents, "
            "declare change intent with scope, compute blast radius "
            "(direct + bounded transitive for high-radius changes), and "
            "return patch budget — all in one call. Requires an existing "
            "analysis run for the given root; call analyze_repository "
            "first if needed. Returns intent_id for finish_controlled_change. "
            "Does not run analysis implicitly."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def start_controlled_change(
        root: RootParam,
        scope: ScopeParam,
        intent: IntentTextParam,
        expected_effects: ExpectedEffectsParam = None,
        on_conflict: OnConflictParam = None,
        strictness: StrictnessParam = "ci",
        ttl_seconds: TtlSecondsParam = None,
        blast_radius_depth: BlastRadiusDepthParam = "auto",
    ) -> dict[str, object]:
        return service.start_controlled_change(
            root=root,
            scope=scope,
            intent=intent,
            expected_effects=expected_effects,
            on_conflict=on_conflict,
            strictness=strictness,
            ttl_seconds=ttl_seconds,
            blast_radius_depth=blast_radius_depth,
        )

    @tool(
        title="Finish Controlled Change",
        description=(
            "Post-edit verify, receipt, and intent clear. Pass after_run_id "
            "when verification.verification_profile requires it. Read "
            "verification.verification_profile for applied checks."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def finish_controlled_change(
        intent_id: IntentIdParam,
        changed_files: ChangedFilesParam = None,
        diff_ref: DiffRefParam = None,
        after_run_id: AfterRunIdParam = None,
        review_text: ReviewTextParam | None = None,
        create_receipt: CreateReceiptParam = True,
        auto_clear: AutoClearParam = True,
        strictness: StrictnessParam = "ci",
    ) -> dict[str, object]:
        return service.finish_controlled_change(
            intent_id=intent_id,
            changed_files=changed_files,
            diff_ref=diff_ref,
            after_run_id=after_run_id,
            review_text=review_text,
            create_receipt=create_receipt,
            auto_clear=auto_clear,
            strictness=strictness,
        )

    @tool(
        title="Manage Change Intent",
        description=(
            "Manage the agent change intent lifecycle for the current MCP "
            "session and optional workspace registry. Actions: 'list_workspace' "
            "to inspect concurrent workspace intents, 'declare' to declare "
            "intended scope before editing, 'get' to retrieve active intent, "
            "'check' to verify actual diff against declared scope, 'clear' to "
            "remove intent, 'renew' to refresh the active lease before long "
            "edits or test runs, 'gc_workspace' to clean stale registry files, "
            "'recover' to explicitly reclaim a recoverable intent, and "
            "'reset_workspace' for interrupted-session recovery. In-memory "
            "intent state remains session-local; workspace coordination state "
            "is ephemeral under .cache/codeclone/intents/."
        ),
        annotations=session_tool,
        structured_output=True,
    )
    def manage_change_intent(
        action: ManageActionParam,
        run_id: RunIdParam = None,
        intent_id: OptionalIntentIdParam = None,
        scope: OptionalScopeParam = None,
        intent: OptionalIntentTextParam = None,
        expected_effects: ExpectedEffectsParam = None,
        diff_ref: DiffRefParam = None,
        changed_files: ChangedFilesParam = None,
        root: OptionalRootParam = None,
        ttl_seconds: TtlSecondsParam = None,
        lease_seconds: LeaseSecondsParam = None,
        on_conflict: OnConflictParam = None,
    ) -> dict[str, object]:
        return service.manage_change_intent(
            action=action,
            run_id=run_id,
            intent_id=intent_id,
            scope=scope,
            intent=intent,
            expected_effects=expected_effects,
            diff_ref=diff_ref,
            changed_files=changed_files,
            root=root,
            ttl_seconds=ttl_seconds,
            lease_seconds=lease_seconds,
            on_conflict=on_conflict,
        )

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
        description="Canonical JSON summary for the latest run in this MCP session.",
        mime_type="application/json",
    )
    def latest_summary_resource() -> str:
        return service.read_resource("codeclone://latest/summary")

    @resource(
        "codeclone://latest/report.json",
        title="Latest Canonical Report",
        description="Canonical JSON report for the latest run in this MCP session.",
        mime_type="application/json",
    )
    def latest_report_resource() -> str:
        return service.read_resource("codeclone://latest/report.json")

    @resource(
        "codeclone://latest/health",
        title="Latest Health Snapshot",
        description="Health snapshot for the latest run in this MCP session.",
        mime_type="application/json",
    )
    def latest_health_resource() -> str:
        return service.read_resource("codeclone://latest/health")

    @resource(
        "codeclone://latest/gates",
        title="Latest Gate Evaluation",
        description="Gate evaluation for the latest run in this MCP session.",
        mime_type="application/json",
    )
    def latest_gates_resource() -> str:
        return service.read_resource("codeclone://latest/gates")

    @resource(
        "codeclone://latest/changed",
        title="Latest Changed Findings",
        description=(
            "Changed-files projection for the latest diff-aware run in this session."
        ),
        mime_type="application/json",
    )
    def latest_changed_resource() -> str:
        return service.read_resource("codeclone://latest/changed")

    @resource(
        "codeclone://latest/triage",
        title="Latest Production Triage",
        description="Production triage for the latest run in this MCP session.",
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
        default=DEFAULT_MCP_HOST,
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
        default=DEFAULT_MCP_PORT,
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
        default=DEFAULT_MCP_JSON_RESPONSE,
        help="Use JSON responses for streamable-http transport.",
    )
    parser.add_argument(
        "--stateless-http",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_MCP_STATELESS_HTTP,
        help="Use stateless Streamable HTTP mode when transport is streamable-http.",
    )
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_MCP_DEBUG,
        help="Enable FastMCP debug mode.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=DEFAULT_MCP_LOG_LEVEL,
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


def _install_sigterm_handler() -> None:
    """Convert SIGTERM to SystemExit so async teardown runs.

    Python's default SIGTERM handler (SIG_DFL) terminates the process
    immediately — no ``finally`` blocks, no ``atexit``, no async
    context manager teardown.  By raising :class:`SystemExit`, the
    event loop unwinds normally and the FastMCP lifespan teardown
    (which cleans workspace intent files) gets a chance to execute.

    Only installed on platforms that support SIGTERM (not Windows).
    """
    import signal as _signal

    if not hasattr(_signal, "SIGTERM"):
        return  # pragma: no cover

    def _handler(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    _signal.signal(_signal.SIGTERM, _handler)


def main() -> None:
    _install_sigterm_handler()
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
