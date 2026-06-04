# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, TypeVar

from ... import __version__
from ...contracts import DEFAULT_COVERAGE_MIN, DOCS_URL
from .auth import (
    MCP_AUTH_TOKEN_ENV,
    MCPAuthConfigurationError,
    StaticBearerTokenVerifier,
    build_http_auth_settings,
    validated_mcp_auth_token,
)
from .messages import errors as err_msgs
from .messages import instructions as mcp_instructions
from .messages import resources as mcp_resources
from .messages import tools as mcp_tools
from .messages.params import (
    AfterRunIdParam,
    AllowExternalArtifactsParam,
    AnalysisModeParam,
    ApiSurfaceParam,
    AuditPathOverrideParam,
    AuditTrailLimitParam,
    AutoClearParam,
    BeforeRunIdParam,
    BlastDepthParam,
    BlastRadiusDepthParam,
    CachePolicyParam,
    CategoryParam,
    ChangedFilesParam,
    ChangedPathsParam,
    ClaimsTextParam,
    CloneTypeParam,
    CompareFocusParam,
    ConfirmationNonceParam,
    CoverageMinParam,
    CoverageXmlParam,
    CreateReceiptParam,
    DetailLevelParam,
    DiffRefParam,
    DirtyScopePolicyParam,
    ExcludeReviewedParam,
    ExpectedEffectsParam,
    FamilyParam,
    FilesParam,
    FindingFamilyParam,
    FindingIdParam,
    FinishReviewTextParam,
    GateBoolParam,
    GateIntParam,
    GitDiffRefParam,
    GovernanceActorParam,
    GovernanceDecisionParam,
    GovernanceProofParam,
    GovernanceProtocolParam,
    GovernanceTicketParam,
    HelpDetailParam,
    HelpTopicParam,
    HotspotKindParam,
    IdeGovernanceClientNameParam,
    IdeGovernanceClientVersionParam,
    IdeGovernanceKeyParam,
    IncludeBlastRadiusParam,
    IncludeDraftsParam,
    IncludeParam,
    IncludePatchContractParam,
    IncludeStaleParam,
    IntentIdParam,
    IntentTextParam,
    LeaseSecondsParam,
    LimitParam,
    ManageActionParam,
    ManageMemoryActionParam,
    MaxHotspotsParam,
    MaxResultsParam,
    MaxSizeMbParam,
    MaxSuggestionsParam,
    MemoryClaimsTextParam,
    MemoryDetailLevelParam,
    MemoryFiltersParam,
    MemoryMaxRecordsParam,
    MemoryPathParam,
    MemoryQueryModeParam,
    MemoryRecordIdParam,
    MemoryRecordTypeParam,
    MemoryScopeListParam,
    MemorySearchQueryParam,
    MemoryStatementParam,
    MemorySymbolParam,
    MemorySymbolsParam,
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
    PatchHealthDeltaParam,
    PatchModeParam,
    PathFilterParam,
    PrFormatParam,
    ProcessesParam,
    ProposeMemoryParam,
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
    SemanticParam,
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
        raise MCPDependencyError(mcp_instructions.MCP_INSTALL_HINT) from exc
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
        err_msgs.invalid_choice(
            "analysis_mode",
            value,
            ("clones_only", "full"),
        )
    )


def _validated_cache_policy(value: str) -> CachePolicy:
    if value == "reuse":
        return "reuse"
    if value == "off":
        return "off"
    if value == "refresh":
        raise MCPServiceContractError(err_msgs.CACHE_POLICY_CLI_ONLY)
    raise MCPServiceContractError(
        err_msgs.invalid_choice("cache_policy", value, ("off", "reuse"))
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
    ide_governance_channel: bool = False,
    auth_token: str | None = None,
) -> FastMCP:
    """Build and register the local read-only CodeClone FastMCP server."""

    runtime_fastmcp, read_only_tool, analysis_tool, session_tool = _load_mcp_runtime()
    service = CodeCloneMCPService(
        history_limit=_validated_history_limit(history_limit),
        ide_governance_channel=ide_governance_channel,
    )

    @asynccontextmanager
    async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, object]]:
        yield {}
        service.shutdown_cleanup()

    token_verifier = None
    auth_settings = None
    if auth_token is not None:
        token_verifier = StaticBearerTokenVerifier(auth_token)
        auth_settings = build_http_auth_settings(host=host, port=port)

    mcp = runtime_fastmcp(
        name="CodeClone",
        instructions=mcp_instructions.SERVER_INSTRUCTIONS,
        lifespan=_lifespan,
        website_url=DOCS_URL,
        host=host,
        port=port,
        json_response=json_response,
        stateless_http=stateless_http,
        debug=debug,
        log_level=log_level,
        dependencies=(f"codeclone=={__version__}",),
        token_verifier=token_verifier,
        auth=auth_settings,
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
        title=mcp_tools.TITLE_ANALYZE_REPOSITORY,
        description=mcp_tools.ANALYZE_REPOSITORY,
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
        allow_external_artifacts: AllowExternalArtifactsParam = False,
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
                allow_external_artifacts=allow_external_artifacts,
            )
        )

    @tool(
        title=mcp_tools.TITLE_ANALYZE_CHANGED_PATHS,
        description=mcp_tools.ANALYZE_CHANGED_PATHS,
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
        allow_external_artifacts: AllowExternalArtifactsParam = False,
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
                allow_external_artifacts=allow_external_artifacts,
            )
        )

    @tool(
        title=mcp_tools.TITLE_GET_RUN_SUMMARY,
        description=mcp_tools.GET_RUN_SUMMARY,
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_run_summary(run_id: RunIdParam = None) -> dict[str, object]:
        return service.get_run_summary(run_id)

    @tool(
        title=mcp_tools.TITLE_GET_PRODUCTION_TRIAGE,
        description=mcp_tools.GET_PRODUCTION_TRIAGE,
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
        title=mcp_tools.TITLE_GET_BLAST_RADIUS,
        description=mcp_tools.GET_BLAST_RADIUS,
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
        title=mcp_tools.TITLE_GET_RELEVANT_MEMORY,
        description=mcp_tools.GET_RELEVANT_MEMORY,
        annotations=read_only_tool,
        structured_output=True,
    )
    def get_relevant_memory(
        root: RootParam,
        scope: MemoryScopeListParam = None,
        intent_id: OptionalIntentIdParam = None,
        symbols: MemorySymbolsParam = None,
        max_records: MemoryMaxRecordsParam = 20,
        include_stale: IncludeStaleParam = False,
        include_drafts: IncludeDraftsParam = False,
        detail_level: MemoryDetailLevelParam = "compact",
    ) -> dict[str, object]:
        return service.get_relevant_memory(
            root=root,
            scope=scope,
            intent_id=intent_id,
            symbols=symbols,
            max_records=max_records,
            include_stale=include_stale,
            include_drafts=include_drafts,
            detail_level=detail_level,
        )

    @tool(
        title=mcp_tools.TITLE_QUERY_ENGINEERING_MEMORY,
        description=mcp_tools.QUERY_ENGINEERING_MEMORY,
        annotations=read_only_tool,
        structured_output=True,
    )
    def query_engineering_memory(
        root: RootParam,
        mode: MemoryQueryModeParam,
        record_id: MemoryRecordIdParam = None,
        path: MemoryPathParam = None,
        symbol: MemorySymbolParam = None,
        query: MemorySearchQueryParam = None,
        scope: MemoryScopeListParam = None,
        filters: MemoryFiltersParam = None,
        max_results: MemoryMaxRecordsParam = 20,
        include_stale: IncludeStaleParam = False,
        include_drafts: IncludeDraftsParam = False,
        detail_level: MemoryDetailLevelParam = "compact",
        semantic: SemanticParam = False,
    ) -> dict[str, object]:
        return service.query_engineering_memory(
            root=root,
            mode=mode,
            record_id=record_id,
            path=path,
            symbol=symbol,
            query=query,
            scope=scope,
            filters=filters,
            max_results=max_results,
            include_stale=include_stale,
            include_drafts=include_drafts,
            detail_level=detail_level,
            semantic=semantic,
        )

    @tool(
        title=mcp_tools.TITLE_MANAGE_ENGINEERING_MEMORY,
        description=mcp_tools.MANAGE_ENGINEERING_MEMORY,
        annotations=session_tool,
        structured_output=True,
    )
    def manage_engineering_memory(
        root: RootParam,
        action: ManageMemoryActionParam,
        record_type: MemoryRecordTypeParam = None,
        statement: MemoryStatementParam = None,
        subject_path: MemoryPathParam = None,
        text: MemoryClaimsTextParam = None,
        intent_id: OptionalIntentIdParam = None,
        run_id: RunIdParam = None,
        record_id: MemoryRecordIdParam = None,
        decision: GovernanceDecisionParam = None,
        ide_governance_key: IdeGovernanceKeyParam = None,
        client_name: IdeGovernanceClientNameParam = None,
        client_version: IdeGovernanceClientVersionParam = None,
        governance_ticket: GovernanceTicketParam = None,
        confirmation_nonce: ConfirmationNonceParam = None,
        proof: GovernanceProofParam = None,
        actor: GovernanceActorParam = None,
        protocol: GovernanceProtocolParam = None,
    ) -> dict[str, object]:
        return service.manage_engineering_memory(
            root=root,
            action=action,
            record_type=record_type,
            statement=statement,
            subject_path=subject_path,
            text=text,
            intent_id=intent_id,
            run_id=run_id,
            record_id=record_id,
            decision=decision,
            ide_governance_key=ide_governance_key,
            client_name=client_name,
            client_version=client_version,
            governance_ticket=governance_ticket,
            confirmation_nonce=confirmation_nonce,
            proof=proof,
            actor=actor,
            protocol=protocol,
        )

    @tool(
        title=mcp_tools.TITLE_CHECK_PATCH_CONTRACT,
        description=mcp_tools.CHECK_PATCH_CONTRACT,
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
        title=mcp_tools.TITLE_CREATE_REVIEW_RECEIPT,
        description=mcp_tools.CREATE_REVIEW_RECEIPT,
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
        title=mcp_tools.TITLE_VALIDATE_REVIEW_CLAIMS,
        description=mcp_tools.VALIDATE_REVIEW_CLAIMS,
        annotations=read_only_tool,
        structured_output=True,
    )
    def validate_review_claims(
        text: ReviewTextParam,
        run_id: RunIdParam = None,
        require_citations: RequireCitationsParam = True,
        patch_health_delta: PatchHealthDeltaParam = None,
    ) -> dict[str, object]:
        return service.validate_review_claims(
            text=text,
            run_id=run_id,
            require_citations=require_citations,
            patch_health_delta=patch_health_delta,
        )

    @tool(
        title=mcp_tools.TITLE_HELP,
        description=mcp_tools.HELP,
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
        title=mcp_tools.TITLE_EVALUATE_GATES,
        description=mcp_tools.EVALUATE_GATES,
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
        title=mcp_tools.TITLE_GET_REPORT_SECTION,
        description=mcp_tools.GET_REPORT_SECTION,
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
        title=mcp_tools.TITLE_LIST_FINDINGS,
        description=mcp_tools.LIST_FINDINGS,
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
        title=mcp_tools.TITLE_GET_FINDING,
        description=mcp_tools.GET_FINDING,
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
        title=mcp_tools.TITLE_GET_REMEDIATION,
        description=mcp_tools.GET_REMEDIATION,
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
        title=mcp_tools.TITLE_LIST_HOTSPOTS,
        description=mcp_tools.LIST_HOTSPOTS,
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
        title=mcp_tools.TITLE_COMPARE_RUNS,
        description=mcp_tools.COMPARE_RUNS,
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
        title=mcp_tools.TITLE_CHECK_COMPLEXITY,
        description=mcp_tools.CHECK_COMPLEXITY,
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
        title=mcp_tools.TITLE_CHECK_CLONES,
        description=mcp_tools.CHECK_CLONES,
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
        title=mcp_tools.TITLE_CHECK_COUPLING,
        description=mcp_tools.CHECK_COUPLING,
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
        title=mcp_tools.TITLE_CHECK_COHESION,
        description=mcp_tools.CHECK_COHESION,
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
        title=mcp_tools.TITLE_CHECK_DEAD_CODE,
        description=mcp_tools.CHECK_DEAD_CODE,
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
        title=mcp_tools.TITLE_GENERATE_PR_SUMMARY,
        description=mcp_tools.GENERATE_PR_SUMMARY,
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
        title=mcp_tools.TITLE_MARK_FINDING_REVIEWED,
        description=mcp_tools.MARK_FINDING_REVIEWED,
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
        title=mcp_tools.TITLE_LIST_REVIEWED_FINDINGS,
        description=mcp_tools.LIST_REVIEWED_FINDINGS,
        annotations=read_only_tool,
        structured_output=True,
    )
    def list_reviewed_findings(run_id: RunIdParam = None) -> dict[str, object]:
        return service.list_reviewed_findings(run_id=run_id)

    @tool(
        title=mcp_tools.TITLE_START_CONTROLLED_CHANGE,
        description=mcp_tools.START_CONTROLLED_CHANGE,
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
        dirty_scope_policy: DirtyScopePolicyParam = "block",
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
            dirty_scope_policy=dirty_scope_policy,
        )

    @tool(
        title=mcp_tools.TITLE_FINISH_CONTROLLED_CHANGE,
        description=mcp_tools.FINISH_CONTROLLED_CHANGE,
        annotations=session_tool,
        structured_output=True,
    )
    def finish_controlled_change(
        intent_id: IntentIdParam,
        changed_files: ChangedFilesParam = None,
        diff_ref: DiffRefParam = None,
        after_run_id: AfterRunIdParam = None,
        review_text: FinishReviewTextParam = None,
        claims_text: ClaimsTextParam = None,
        create_receipt: CreateReceiptParam = True,
        auto_clear: AutoClearParam = True,
        strictness: StrictnessParam = "ci",
        propose_memory: ProposeMemoryParam = False,
        detail_level: DetailLevelParam = "summary",
    ) -> dict[str, object]:
        return service.finish_controlled_change(
            intent_id=intent_id,
            changed_files=changed_files,
            diff_ref=diff_ref,
            after_run_id=after_run_id,
            review_text=review_text,
            claims_text=claims_text,
            create_receipt=create_receipt,
            auto_clear=auto_clear,
            strictness=strictness,
            propose_memory=propose_memory,
            detail_level=detail_level,
        )

    @tool(
        title=mcp_tools.TITLE_MANAGE_CHANGE_INTENT,
        description=mcp_tools.MANAGE_CHANGE_INTENT,
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
        title=mcp_tools.TITLE_CLEAR_SESSION_RUNS,
        description=mcp_tools.CLEAR_SESSION_RUNS,
        annotations=session_tool,
        structured_output=True,
    )
    def clear_session_runs() -> dict[str, object]:
        return service.clear_session_runs()

    if ide_governance_channel:

        @tool(
            title=mcp_tools.TITLE_GET_WORKSPACE_SESSION_STATS,
            description=mcp_tools.GET_WORKSPACE_SESSION_STATS,
            annotations=read_only_tool,
            structured_output=True,
        )
        def get_workspace_session_stats(root: RootParam) -> dict[str, object]:
            return service.get_workspace_session_stats(root=root)

        @tool(
            title=mcp_tools.TITLE_GET_CONTROLLER_AUDIT_TRAIL,
            description=mcp_tools.GET_CONTROLLER_AUDIT_TRAIL,
            annotations=read_only_tool,
            structured_output=True,
        )
        def get_controller_audit_trail(
            root: RootParam,
            limit: AuditTrailLimitParam = 50,
            audit_path: AuditPathOverrideParam = None,
        ) -> dict[str, object]:
            return service.get_controller_audit_trail(
                root=root,
                limit=limit,
                audit_path=audit_path,
            )

    @resource(
        "codeclone://latest/summary",
        title=mcp_resources.TITLE_LATEST_SUMMARY,
        description=mcp_resources.LATEST_SUMMARY,
        mime_type="application/json",
    )
    def latest_summary_resource() -> str:
        return service.read_resource("codeclone://latest/summary")

    @resource(
        "codeclone://latest/report.json",
        title=mcp_resources.TITLE_LATEST_REPORT,
        description=mcp_resources.LATEST_REPORT,
        mime_type="application/json",
    )
    def latest_report_resource() -> str:
        return service.read_resource("codeclone://latest/report.json")

    @resource(
        "codeclone://latest/health",
        title=mcp_resources.TITLE_LATEST_HEALTH,
        description=mcp_resources.LATEST_HEALTH,
        mime_type="application/json",
    )
    def latest_health_resource() -> str:
        return service.read_resource("codeclone://latest/health")

    @resource(
        "codeclone://latest/gates",
        title=mcp_resources.TITLE_LATEST_GATES,
        description=mcp_resources.LATEST_GATES,
        mime_type="application/json",
    )
    def latest_gates_resource() -> str:
        return service.read_resource("codeclone://latest/gates")

    @resource(
        "codeclone://latest/changed",
        title=mcp_resources.TITLE_LATEST_CHANGED,
        description=mcp_resources.LATEST_CHANGED,
        mime_type="application/json",
    )
    def latest_changed_resource() -> str:
        return service.read_resource("codeclone://latest/changed")

    @resource(
        "codeclone://latest/triage",
        title=mcp_resources.TITLE_LATEST_TRIAGE,
        description=mcp_resources.LATEST_TRIAGE,
        mime_type="application/json",
    )
    def latest_triage_resource() -> str:
        return service.read_resource("codeclone://latest/triage")

    @resource(
        "codeclone://schema",
        title=mcp_resources.TITLE_REPORT_SCHEMA,
        description=mcp_resources.REPORT_SCHEMA,
        mime_type="application/json",
    )
    def schema_resource() -> str:
        return service.read_resource("codeclone://schema")

    @resource(
        "codeclone://runs/{run_id}/summary",
        title=mcp_resources.TITLE_RUN_SUMMARY,
        description=mcp_resources.RUN_SUMMARY,
        mime_type="application/json",
    )
    def run_summary_resource(run_id: str) -> str:
        return service.read_resource(f"codeclone://runs/{run_id}/summary")

    @resource(
        "codeclone://runs/{run_id}/report.json",
        title=mcp_resources.TITLE_RUN_REPORT,
        description=mcp_resources.RUN_REPORT,
        mime_type="application/json",
    )
    def run_report_resource(run_id: str) -> str:
        return service.read_resource(f"codeclone://runs/{run_id}/report.json")

    @resource(
        "codeclone://runs/{run_id}/findings/{finding_id}",
        title=mcp_resources.TITLE_RUN_FINDING,
        description=mcp_resources.RUN_FINDING,
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
            f"HTTP still requires {MCP_AUTH_TOKEN_ENV}."
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
    parser.add_argument(
        "--ide-governance-channel",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable the VS Code IDE governance channel for human "
            "approve/reject/archive via manage_engineering_memory. "
            "Agent launchers must not pass this flag."
        ),
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
                f"Set {MCP_AUTH_TOKEN_ENV} and pass --allow-remote explicitly."
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
    auth_token = None
    if args.transport == "streamable-http":
        try:
            auth_token = validated_mcp_auth_token(os.environ.get(MCP_AUTH_TOKEN_ENV))
        except MCPAuthConfigurationError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
    try:
        server = build_mcp_server(
            history_limit=args.history_limit,
            host=args.host,
            port=args.port,
            json_response=args.json_response,
            stateless_http=args.stateless_http,
            debug=args.debug,
            log_level=args.log_level,
            ide_governance_channel=args.ide_governance_channel,
            auth_token=auth_token,
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
