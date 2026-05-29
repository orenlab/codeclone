# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Concise MCP tool parameter descriptions for JSON Schema export."""

from __future__ import annotations

from typing import Annotated

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
    Field(description="Cobertura XML path; absolute or repo-relative."),
]
CoverageMinParam = Annotated[
    int | None,
    Field(description="Coverage gate minimum percent (0-100)."),
]
OptionalPathParam = Annotated[
    str | None,
    Field(description="Repo-relative or absolute artifact path."),
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
ReviewTextParam = Annotated[
    str,
    Field(description="Review claims text to validate against the run."),
]
RequireCitationsParam = Annotated[
    bool,
    Field(description="Require finding ids or metric citations in text."),
]
HelpTopicParam = Annotated[
    str,
    Field(
        description=(
            "workflow, analysis_profile, baseline, coverage, change_control, "
            "trust_boundaries, ..."
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
            "derived, integrity, or all."
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
