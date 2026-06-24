# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""MCP tool parameter Field descriptions for JSON Schema export."""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field

RootParam = Annotated[str, Field(description="Absolute repository root path.")]
OptionalRootParam = Annotated[
    str | None,
    Field(description="Absolute repository root when resolving run by root."),
]
RunIdParam = Annotated[
    str | None,
    Field(description="8-char or full run id; latest run when omitted."),
]
RunIdRequiredParam = Annotated[
    str,
    Field(description="8-char or full run id from analyze response."),
]
Facet = Literal[
    "module_role",
    "imports",
    "importers",
    "callers",
    "callees",
    "references",
    "public_surface",
    "blast_radius",
    "tests",
    "contract_tests",
    "test_callers",
    "docs",
    "memory",
    "trajectories",
    "experiences",
    "memory_conflicts",
    "definition_sites",
    "persistence_path_callers",
    "serialization_path_callers",
    "deserialization_path_callers",
    "store_api_consumers",
    "scope",
    "review_context",
    "baseline_sensitive_findings",
    "version_constants",
    "dataflow",
]
VALID_FACETS = frozenset(get_args(Facet))
ContextPathsParam = Annotated[
    list[str] | None,
    Field(description="Repo-relative implementation-context subject paths."),
]
ContextSymbolsParam = Annotated[
    list[str] | None,
    Field(
        description=(
            "module:symbol qualnames to resolve as context subjects "
            "(colon separator, for example pkg.mod:func)."
        ),
    ),
]
ChangedScopeParam = Annotated[
    bool,
    Field(description="Use the current git-dirty scope as the context subject."),
]
ContextQueryParam = Annotated[
    str | None,
    Field(
        description=(
            "Name search query across analyzed definitions, call targets, and "
            "imports; mutually exclusive with paths, symbols, and changed_scope."
        )
    ),
]
ContextModeParam = Annotated[
    Literal["implementation", "impact", "contract"],
    Field(description="implementation, impact, or contract context mode."),
]
FacetIncludeParam = Annotated[
    list[Facet] | None,
    Field(description="Optional closed set of implementation-context facets."),
]
ContextDepthParam = Annotated[
    int,
    Field(
        ge=0,
        le=3,
        description="Bounded structural traversal depth from 0 through 3.",
    ),
]
ContextDetailLevelParam = Annotated[
    Literal["compact", "normal", "full"],
    Field(description="compact, normal, or full context detail level."),
]
ContextBudgetParam = Annotated[
    int,
    Field(
        ge=1,
        le=200,
        description="Global maximum emitted context entries (1-200).",
    ),
]
AnalysisModeParam = Annotated[
    str,
    Field(description="full: clones+metrics. clones_only: clones without metrics."),
]
RespectPyprojectParam = Annotated[
    bool,
    Field(description="Load [tool.codeclone] thresholds from pyproject when true."),
]
ChangedPathsParam = Annotated[
    list[str] | None,
    Field(description="Repo-relative paths; mutually exclusive with git_diff_ref."),
]
GitDiffRefParam = Annotated[
    str | None,
    Field(description="Safe git revision for changed files; not with changed_paths."),
]
ProcessesParam = Annotated[
    int | None,
    Field(description="Parallel workers override; capped by host and 64."),
]
ThresholdIntParam = Annotated[
    int | None,
    Field(description="Optional analysis threshold override."),
]
ApiSurfaceParam = Annotated[
    bool | None,
    Field(description="Enable API surface metrics when true."),
]
CoverageXmlParam = Annotated[
    str | None,
    Field(
        description=(
            "Cobertura XML path. Absolute/out-of-repo paths require "
            "allow_external_artifacts=true."
        )
    ),
]
CoverageMinParam = Annotated[
    int | None,
    Field(description="Coverage gate minimum percent (0-100)."),
]
OptionalPathParam = Annotated[
    str | None,
    Field(
        description=(
            "Repo-relative artifact path. Absolute/out-of-repo paths require "
            "allow_external_artifacts=true."
        )
    ),
]
AllowExternalArtifactsParam = Annotated[
    bool,
    Field(
        description=(
            "Allow optional artifact paths (baseline_path, metrics_baseline_path, "
            "cache_path, coverage_xml) to be absolute or outside the repository."
        )
    ),
]
MaxSizeMbParam = Annotated[
    int | None,
    Field(description="Max artifact size in megabytes."),
]
CachePolicyParam = Annotated[
    str,
    Field(description="reuse: read cache. off: skip cache. MCP read-only."),
]
FilesParam = Annotated[
    list[str],
    Field(description="Repo-relative files to inspect for blast radius."),
]
BlastDepthParam = Annotated[
    str,
    Field(description="direct, transitive, or auto blast-radius depth."),
]
IncludeParam = Annotated[
    list[str] | None,
    Field(description="Optional blast-radius include filters."),
]
PatchModeParam = Annotated[
    str,
    Field(description="budget: pre-edit gate preview. verify: post-edit check."),
]
StrictnessParam = Annotated[
    str,
    Field(description="ci, relaxed, or strict patch-contract profile."),
]
DiffRefParam = Annotated[
    str | None,
    Field(description="Git revision for scope or verify evidence."),
]
ChangedFilesParam = Annotated[
    list[str] | None,
    Field(description="Repo-relative changed files for scope or verify."),
]
IntentIdParam = Annotated[str, Field(description="Intent id from start or declare.")]
OptionalIntentIdParam = Annotated[
    str | None,
    Field(description="Active or queued intent id when required by action."),
]
ReceiptFormatParam = Annotated[
    str,
    Field(description="markdown or json receipt output."),
]
ReceiptRetrievalFormatParam = Annotated[
    str,
    Field(
        description="Stored receipt output: structured (typed, default) or markdown.",
    ),
]
ReceiptDigestParam = Annotated[
    str | None,
    Field(
        description="Exact receipt digest (sha256 hex value) for durable lookup.",
    ),
]
PatchTrailDigestParam = Annotated[
    str | None,
    Field(
        description="Exact patch-trail digest (sha256 hex) for durable lookup.",
    ),
]
ReviewTextParam = Annotated[
    str,
    Field(description="Review claims text to validate against the run."),
]
FinishReviewTextParam = Annotated[
    str | None,
    Field(
        description=(
            "Optional human review note for finish output; not claim-validated. "
            "Use claims_text for text that should be checked."
        ),
    ),
]
ClaimsTextParam = Annotated[
    str | None,
    Field(description="Optional claims text to validate against the run."),
]
RequireCitationsParam = Annotated[
    bool,
    Field(description="Require finding ids or metric citations in text."),
]
PatchHealthDeltaParam = Annotated[
    int | None,
    Field(
        description=(
            "Optional health delta from check_patch_contract verify "
            "(after minus before). Enables health-regression overclaim checks."
        ),
    ),
]
HelpTopicParam = Annotated[
    str,
    Field(
        description=(
            "workflow, analysis_profile, suppressions, baseline, coverage, "
            "latest_runs, review_state, changed_scope, change_control, "
            "trust_boundaries, engineering_memory, implementation_context, "
            "verification_profiles, observability"
        )
    ),
]
HelpDetailParam = Annotated[
    str,
    Field(description="compact includes anti_patterns; normal adds warnings."),
]
GateIntParam = Annotated[
    int,
    Field(description="Gate threshold; -1 disables that gate."),
]
GateBoolParam = Annotated[bool, Field(description="Enable this gate when true.")]
ReportSectionParam = Annotated[
    str,
    Field(
        description=(
            "meta, inventory, findings, metrics, metrics_detail, changed, "
            "derived, module_map, integrity, or all."
        )
    ),
]
FamilyParam = Annotated[
    str | None,
    Field(description="Metrics or finding family filter."),
]
PathFilterParam = Annotated[
    str | None,
    Field(description="Repo-relative module or file path filter."),
]
OffsetParam = Annotated[int, Field(description="Pagination offset.")]
LimitParam = Annotated[int, Field(description="Pagination limit.")]
FindingFamilyParam = Annotated[
    str,
    Field(description="all, clone, structural, dead_code, or design."),
]
CategoryParam = Annotated[str | None, Field(description="Finding category filter.")]
SeverityParam = Annotated[str | None, Field(description="critical, warning, or info.")]
SourceKindParam = Annotated[
    str | None,
    Field(description="production, tests, fixtures, mixed, or other."),
]
NoveltyParam = Annotated[str, Field(description="all, new, or known vs baseline.")]
SortByParam = Annotated[
    str,
    Field(description="default, priority, severity, or spread."),
]
DetailLevelParam = Annotated[
    str,
    Field(description="summary, normal, or full detail level."),
]
PatchTrailDetailParam = Annotated[
    str,
    Field(description="summary or full patch_trail payload on finish."),
]
ExcludeReviewedParam = Annotated[
    bool,
    Field(description="Omit session-marked reviewed findings when true."),
]
MaxResultsParam = Annotated[
    int | None,
    Field(description="Optional hard cap on returned items."),
]
FindingIdParam = Annotated[
    str, Field(description="Short or full canonical finding id.")
]
HotspotKindParam = Annotated[
    str,
    Field(
        description=(
            "most_actionable, highest_spread, highest_priority, "
            "production_hotspots, or test_fixture_hotspots."
        )
    ),
]
CompareFocusParam = Annotated[
    str,
    Field(description="all, clones, structural, or metrics comparison focus."),
]
MaxHotspotsParam = Annotated[
    int, Field(description="Max production hotspots returned.")
]
MaxSuggestionsParam = Annotated[
    int, Field(description="Max production suggestions returned.")
]
CloneTypeParam = Annotated[
    str | None, Field(description="function, block, or segment.")
]
MinComplexityParam = Annotated[
    int | None,
    Field(description="Minimum cyclomatic complexity filter."),
]
MinSeverityParam = Annotated[
    str | None,
    Field(description="Minimum dead-code severity filter."),
]
PrFormatParam = Annotated[
    str,
    Field(description="markdown (preferred) or json PR summary."),
]
ReviewNoteParam = Annotated[
    str | None,
    Field(description="Optional session-local review note."),
]
ScopeParam = Annotated[
    dict[str, object],
    Field(
        description=(
            "Scope object with allowed_files, optional allowed_related, forbidden."
        )
    ),
]
IntentTextParam = Annotated[
    str, Field(description="Short description of planned edit.")
]
ExpectedEffectsParam = Annotated[
    list[str] | None,
    Field(description="Optional expected patch effects for review."),
]
OnConflictParam = Annotated[
    str | None,
    Field(description="queue to wait on overlapping workspace intents."),
]
TtlSecondsParam = Annotated[
    int | None,
    Field(description="Intent TTL seconds; default 3600."),
]
BlastRadiusDepthParam = Annotated[
    str,
    Field(description="auto, direct, or transitive pre-edit blast radius."),
]
DirtyScopePolicyParam = Annotated[
    str,
    Field(
        description=(
            "block (default) or continue_own_wip when uncommitted changes "
            "already overlap declared scope."
        ),
    ),
]
AfterRunIdParam = Annotated[
    str | None,
    Field(description="Post-edit analyze run id for structural verify."),
]
BeforeRunIdParam = Annotated[
    str | None,
    Field(description="Pre-edit analyze run id or intent-resolved before run."),
]
CreateReceiptParam = Annotated[
    bool,
    Field(description="Generate review receipt on accepted finish."),
]
AutoClearParam = Annotated[
    bool,
    Field(description="Clear intent after accepted finish when true."),
]
IncludeBlastRadiusParam = Annotated[
    bool,
    Field(description="Include blast radius section in receipt."),
]
IncludePatchContractParam = Annotated[
    bool,
    Field(description="Include patch contract section in receipt."),
]
OptionalScopeParam = Annotated[
    dict[str, object] | None,
    Field(description="Scope for declare: allowed_files, allowed_related, forbidden."),
]
OptionalIntentTextParam = Annotated[
    str | None,
    Field(description="Intent description for declare action."),
]
ManageActionParam = Annotated[
    str,
    Field(
        description=(
            "list_workspace, declare, get, check, clear, renew, promote, "
            "recover, gc_workspace, reset_workspace."
        )
    ),
]
LeaseSecondsParam = Annotated[
    int | None,
    Field(description="Lease renewal seconds for renew action."),
]
MemoryDetailLevelParam = Annotated[
    str,
    Field(
        description=(
            "compact (default) returns statement previews without payload; "
            "full returns complete statement and payload. mode=get always returns full."
        ),
    ),
]
MemoryScopeListParam = Annotated[
    list[str] | None,
    Field(description="Repo-relative scope paths for engineering memory retrieval."),
]
MemorySymbolsParam = Annotated[
    list[str] | None,
    Field(description="Optional symbol keys for engineering memory retrieval."),
]
MemoryQueryModeParam = Annotated[
    str,
    Field(
        description=(
            "search, get, for_path, for_symbol, stale, drafts, coverage, status, "
            "trajectory_status, trajectory_search, trajectory_get, "
            "trajectory_anomalies, trajectory_agents, or trajectory_dashboard."
        ),
    ),
]
MemorySearchQueryParam = Annotated[
    str | None,
    Field(description="Keyword query for mode=search or mode=trajectory_search."),
]
MemoryRecordIdParam = Annotated[
    str | None,
    Field(
        description=(
            "Record id for mode=get or IDE governance actions; trajectory id for "
            "mode=trajectory_get."
        ),
    ),
]
MemoryPathParam = Annotated[
    str | None,
    Field(
        description=(
            "Repo-relative subject path for manage_engineering_memory "
            "action=record_candidate (required for record_candidate)."
        ),
    ),
]
MemorySymbolParam = Annotated[
    str | None,
    Field(description="Symbol qualname for mode=for_symbol."),
]
MemoryFiltersParam = Annotated[
    dict[str, object] | None,
    Field(
        description=(
            "Optional filters: types, statuses, confidences, match_mode "
            "(any|all, search mode only), include_routine (trajectory_search, "
            "trajectory_anomalies, trajectory_agents, trajectory_dashboard; "
            "default false excludes run:* routine workflows)."
        ),
    ),
]
IncludeStaleParam = Annotated[
    bool,
    Field(description="Include stale engineering memory records."),
]
SemanticParam = Annotated[
    bool,
    Field(
        description=(
            "Blend semantic recall into mode=search (FTS plus semantic, "
            "re-ranked); audit incidents and trajectory precedents are returned "
            "typed-separate. Requires the optional index; falls back to FTS-only "
            "when unavailable."
        )
    ),
]
IncludeDraftsParam = Annotated[
    bool,
    Field(
        description=(
            "Include draft engineering memory records. Defaults false for search; "
            "get_relevant_memory with scope or intent_id includes drafts "
            "automatically; query_engineering_memory for_path/for_symbol includes "
            "drafts without setting this flag."
        ),
    ),
]
MemoryMaxRecordsParam = Annotated[
    int,
    Field(description="Maximum engineering memory records to return."),
]
AuditTrailLimitParam = Annotated[
    int,
    Field(
        description=(
            "Maximum recent audit events for IDE-only get_controller_audit_trail."
        ),
    ),
]
AuditPathOverrideParam = Annotated[
    str | None,
    Field(
        description=(
            "Optional audit database path override for IDE-only "
            "get_controller_audit_trail."
        ),
    ),
]
ManageMemoryActionParam = Annotated[
    str,
    Field(
        description=(
            "Agent: record_candidate, promote_experience, validate_claims, "
            "propose_from_receipt, "
            "refresh_from_run, rebuild_semantic_index, rebuild_trajectories, "
            "enqueue_projection_rebuild, projection_rebuild_status, "
            "run_projection_jobs_once. "
            "IDE channel only (VS Code): "
            "register_ide_governance, "
            "prepare_governance, commit_governance. approve/reject/archive are not "
            "available through MCP."
        ),
    ),
]
ManageMemoryExperienceIdParam = Annotated[
    str | None,
    Field(
        description=(
            "Experience id for manage_engineering_memory "
            "action=promote_experience (required for that action)."
        ),
    ),
]
GovernanceDecisionParam = Annotated[
    str | None,
    Field(description="IDE governance decision: approve, reject, or archive."),
]
IdeGovernanceKeyParam = Annotated[
    str | None,
    Field(
        description=(
            "Session-bound IDE governance key (hex, >=32 bytes). VS Code only."
        ),
    ),
]
IdeGovernanceClientNameParam = Annotated[
    str | None,
    Field(description="IDE client name for register_ide_governance."),
]
IdeGovernanceClientVersionParam = Annotated[
    str | None,
    Field(description="IDE client version for register_ide_governance."),
]
GovernanceTicketParam = Annotated[
    str | None,
    Field(description="Single-use governance ticket from prepare_governance."),
]
ConfirmationNonceParam = Annotated[
    str | None,
    Field(description="Nonce from prepare_governance; required for commit."),
]
GovernanceProofParam = Annotated[
    str | None,
    Field(description="HMAC proof for commit_governance (protocol v2)."),
]
GovernanceActorParam = Annotated[
    str | None,
    Field(description="Human actor label stored on the memory revision."),
]
GovernanceProtocolParam = Annotated[
    int | None,
    Field(description="IDE attestation protocol version (currently 2)."),
]
MemoryRecordTypeParam = Annotated[
    str | None,
    Field(description="Memory record type for record_candidate."),
]
MemoryStatementParam = Annotated[
    str | None,
    Field(description="Candidate statement for record_candidate."),
]
MemoryClaimsTextParam = Annotated[
    str | None,
    Field(description="Claims text for validate_claims."),
]
ProposeMemoryParam = Annotated[
    bool,
    Field(
        description=(
            "When true on accepted finish, propose draft memory candidates "
            "and mark scope-linked records stale."
        ),
    ),
]

ObservabilitySectionParam = Annotated[
    str,
    Field(
        description=(
            "Telemetry section to project: summary | slow_operations | "
            "memory_pipeline_cost | db_cost | agent_context | mcp_tool_matrix | "
            "correlated_chains | costly_noops | pipeline | analysis_phase_cost."
        ),
    ),
]
ObservabilityDetailParam = Annotated[
    str,
    Field(
        description=(
            "compact (bounded top rows) or normal (rows up to limit); full "
            "downgrades to normal for aggregate sections."
        ),
    ),
]
ObservabilityLimitParam = Annotated[
    int,
    Field(description="Row cap per section; clamped to [1, 50], else 10."),
]
ObservabilityWindowParam = Annotated[
    str,
    Field(description="'latest' for the recent window, or a correlation_id."),
]
ObservabilityOperationIdParam = Annotated[
    str | None,
    Field(description="Reserved for detail sections; echoed in ignored_parameters."),
]
ObservabilitySpanIdParam = Annotated[
    str | None,
    Field(description="Reserved for detail sections; echoed in ignored_parameters."),
]
