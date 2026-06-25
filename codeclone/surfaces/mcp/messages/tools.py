# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP tool descriptions for FastMCP registration."""

from __future__ import annotations

from typing import Final

ANALYZE_REPOSITORY: Final = (
    "Run a deterministic CodeClone analysis and register it as the "
    "latest MCP run. Pass an absolute repository root; relative roots "
    "like '.' are rejected in MCP. MCP cache_policy accepts reuse or "
    "off only. Start with get_production_triage."
)

ANALYZE_CHANGED_PATHS: Final = (
    "Run changed-files analysis from explicit paths or git diff ref. "
    "Absolute root required. MCP cache_policy: reuse or off. "
    "Response includes next_tool hint."
)

GET_RUN_SUMMARY: Final = (
    "Compact run snapshot for latest or specified run. run_id accepts "
    "8-char short id or full digest."
)

GET_PRODUCTION_TRIAGE: Final = (
    "Return a production-first triage view over a stored run: health, "
    "cache freshness, production hotspots, and production suggestions, "
    "while keeping global source-kind counters visible. Use this as the "
    "default first-pass review on noisy repositories."
)

GET_BLAST_RADIUS: Final = (
    "Return the deterministic structural risk boundary for changing "
    "the given files. Shows direct dependents, clone cohort members, "
    "coverage gaps, actionable do-not-touch paths, and review-only "
    "context. Derived from the canonical report; no new analysis is "
    "performed."
)

GET_BLAST_ARTIFACT: Final = (
    "Fetch a durably stored start-time blast artifact from the audit trail by "
    "run id, blast artifact id, and/or projection digest, exactly as it was "
    "persisted when start_controlled_change produced its slim summary. It is "
    "never re-derived from current state. Returns the full omitted blast "
    "projection for direct/transitive dependents, clone cohorts, review "
    "context, cycles, and risk details. Durability is bounded by audit "
    "retention. Fail-closed statuses: ok, not_found, ambiguous, "
    "digest_mismatch, artifact_id_mismatch, malformed_stored_blast_artifact, "
    "unsupported_format. Read-only; does not mutate repository state."
)

GET_IMPLEMENTATION_CONTEXT: Final = (
    "Return deterministic, bounded implementation context from one existing "
    "analysis run. Resolves explicit repo-relative paths and module:symbol "
    "qualnames, then projects module, dependency, API-surface, call/reference, "
    "blast-radius, cache-origin, and workspace-freshness facts without "
    "re-analysis or edit authorization."
)

GET_RELEVANT_MEMORY: Final = (
    "Return ranked, evidence-linked engineering memory for the declared "
    "edit scope. Requires absolute root (same as analyze_repository). "
    "Pass scope paths and/or an active intent_id from start_controlled_change; "
    "symbols-only retrieval is also supported. Unscoped project-wide retrieval "
    "is rejected — use query_engineering_memory(mode=status|search) instead. "
    "List responses default to compact statement previews; pass detail_level=full "
    "for complete statements. Scoped responses may also include typed "
    "trajectory precedents in trajectories[]; records[] remains memory records "
    "only. When a lane has an omitted tail, continuation.lanes.*.page provides "
    "a digest-bound cursor for get_memory_projection_page. Read-only; does not "
    "mutate the memory database."
)

QUERY_ENGINEERING_MEMORY: Final = (
    "Mode-based engineering memory inspection router. Modes: search, get, "
    "for_path, for_symbol, stale, drafts, coverage, status, trajectory_status, "
    "trajectory_search, trajectory_get, experience_get, trajectory_anomalies, "
    "trajectory_agents, and trajectory_dashboard. List modes default to compact "
    "previews; mode=get and detail_level=full return complete statements. "
    "mode=trajectory_get uses record_id as the trajectory id; "
    "mode=experience_get uses record_id as the experience id. Project root is "
    "not a valid path or coverage scope. Read-only."
)

GET_MEMORY_PROJECTION_PAGE: Final = (
    "Return an exact page for a get_relevant_memory omitted tail using the "
    "digest-bound cursor from continuation.lanes.*.page. The page fails closed "
    "with snapshot_mismatch if the underlying memory projection no longer "
    "matches the cursor identity."
)

MANAGE_ENGINEERING_MEMORY: Final = (
    "Engineering memory governance. Agent actions: refresh_from_run, "
    "record_candidate, promote_experience, validate_claims, propose_from_receipt, "
    "rebuild_semantic_index, rebuild_trajectories, enqueue_projection_rebuild, "
    "projection_rebuild_status, run_projection_jobs_once. "
    "promote_experience(experience_id) turns a distilled experience into a "
    "human-approvable draft. "
    "approve/reject/archive are not available to agents — use VS Code Memory view."
)

CHECK_PATCH_CONTRACT: Final = (
    "Pre-edit budget query (mode='budget') or post-edit structural "
    "verification (mode='verify'). Composes stored runs, gate "
    "evaluation, run comparison, and session-local change intent "
    "without running analysis or mutating repository state."
)

CREATE_REVIEW_RECEIPT: Final = (
    "Generate a deterministic, auditable review receipt from stored "
    "MCP state: report provenance, intent scope, blast radius, "
    "reviewed findings, patch contract status, human decision points, "
    "and claims-not-made. Output markdown or JSON without mutating "
    "repository state."
)

GET_REVIEW_RECEIPT: Final = (
    "Fetch a durably stored review receipt from the audit trail by run id "
    "and/or receipt digest, exactly as it was created. It survives auto_clear "
    "and is never re-derived from current state. Returns the canonical typed "
    "receipt (format='structured', the default) or its rendered markdown "
    "(format='markdown'). At least one lookup key is required; if both are given "
    "they must identify the same receipt. Durability is bounded by audit "
    "retention. Fail-closed statuses: ok, not_found, ambiguous, digest_mismatch, "
    "malformed_stored_receipt, unsupported_format. Read-only; does not mutate "
    "repository state."
)

GET_PATCH_TRAIL: Final = (
    "Fetch a durably stored patch trail from the audit trail by run id and/or "
    "patch-trail digest, exactly as it was computed. It survives auto_clear and "
    "is never re-derived from current state. Returns the full forensic trail "
    "(declared/changed/untouched files, scope check, verification, workspace "
    "hygiene, evidence) that the default response omits or summarizes. At least "
    "one lookup key is required; if both are given they must identify the same "
    "trail. Durability is bounded by audit retention. Fail-closed statuses: ok, "
    "not_found, ambiguous, digest_mismatch, malformed_stored_patch_trail, "
    "unsupported_format. Read-only; does not mutate repository state."
)

VALIDATE_REVIEW_CLAIMS: Final = (
    "Validate cited review text against canonical report semantics. "
    "Detects deterministic mischaracterizations: Security Surfaces "
    "called vulnerabilities, report-only signals called CI failures, "
    "known baseline debt called new relative to baseline, patch-local "
    "regression claims without before/after evidence, dead code claimed "
    "where runtime reachability evidence exists, fixes claimed "
    "without post-patch verification, and regression-free claims when "
    "patch_health_delta is negative. Pass patch_health_delta from "
    "check_patch_contract verify or finish verification.structural_delta. "
    "Structural citation matching; not NLP."
)

HELP: Final = (
    "Bounded workflow/contract guidance with doc links. compact adds "
    "anti_patterns; normal adds warnings. Topics: workflow, analysis_profile, "
    "suppressions, baseline, coverage, latest_runs, review_state, "
    "changed_scope, change_control, trust_boundaries, engineering_memory, "
    "implementation_context, verification_profiles, observability."
)

QUERY_PLATFORM_OBSERVABILITY: Final = (
    "Read-only sectioned diagnostics over CodeClone's own runtime telemetry "
    "(Phase 29). Observability is for CodeClone self-development and "
    "diagnostics. It is NOT part of user-facing CodeClone analysis. It MUST "
    "NOT affect reports, gates, baselines, memory facts, or edit "
    "authorization. A slicer, not a trace export API: each call returns one "
    "bounded section, never the full trace, numeric metrics only (no raw SQL "
    "or payloads). Anti-inference guard: this describes the runtime of "
    "CodeClone itself, not the user repository — high DB queries != repository "
    "bad; high MCP payload != code quality low; hot semantic reindex != unsafe "
    "change. Sections: summary, slow_operations, memory_pipeline_cost, "
    "db_cost, agent_context, mcp_tool_matrix, correlated_chains, costly_noops, "
    "pipeline, analysis_phase_cost. detail_level compact|normal (full "
    "downgrades to normal for aggregate sections). Intended for CodeClone "
    "maintainers and development agents; do not use it to make user-facing "
    "quality claims about a repo."
)

EVALUATE_GATES: Final = (
    "Evaluate CodeClone gate conditions against an existing MCP run without "
    "modifying baselines or exiting the process."
)

GET_REPORT_SECTION: Final = (
    "Return one canonical report section. Prefer metrics, metrics_detail, "
    "changed, findings over all unless necessary."
)

LIST_FINDINGS: Final = (
    "List canonical finding groups with deterministic ordering, optional "
    "filters, pagination, and compact summary cards by default. Prefer "
    "list_hotspots or focused check_* tools for first-pass triage; use "
    "this when you need a broader filtered list."
)

GET_FINDING: Final = (
    "Return a single canonical finding group by short or full id. "
    "Normal detail is the default. Use this after list_hotspots, "
    "list_findings, or check_* instead of requesting larger lists at "
    "higher detail."
)

GET_REMEDIATION: Final = (
    "Return actionable remediation guidance for a single finding. "
    "Normal detail is the default. Use this when you need the fix packet "
    "for one finding without pulling larger detail lists."
)

LIST_HOTSPOTS: Final = (
    "Return one of the derived CodeClone hotlists for the latest or "
    "specified MCP run, using compact summary cards by default. Prefer "
    "this for first-pass triage before broader list_findings calls."
)

COMPARE_RUNS: Final = (
    "Compare two runs by finding ids. run_id accepts short or full ids. "
    "Returns incomparable when roots or settings differ."
)

CHECK_COMPLEXITY: Final = (
    "Return complexity hotspots from a compatible stored run. "
    "Use analyze_repository first if no full run is available. When "
    "filtering by root without run_id, pass an absolute root. Prefer "
    "this narrower tool instead of list_findings when you only need "
    "complexity hotspots."
)

CHECK_CLONES: Final = (
    "Return clone findings from a compatible stored run. "
    "Use analyze_repository first if no compatible run is available. "
    "When filtering by root without run_id, pass an absolute root. "
    "Prefer this narrower tool instead of list_findings when you only need "
    "clone findings."
)

CHECK_COUPLING: Final = (
    "Return coupling hotspots from a compatible stored run. "
    "Use analyze_repository first if no full run is available. When "
    "filtering by root without run_id, pass an absolute root. Prefer "
    "this narrower tool instead of list_findings when you only need "
    "coupling hotspots."
)

CHECK_COHESION: Final = (
    "Return cohesion hotspots from a compatible stored run. "
    "Use analyze_repository first if no full run is available. When "
    "filtering by root without run_id, pass an absolute root. Prefer "
    "this narrower tool instead of list_findings when you only need "
    "cohesion hotspots."
)

CHECK_DEAD_CODE: Final = (
    "Return dead-code findings from a compatible stored run. "
    "Use analyze_repository first if no full run is available. When "
    "filtering by root without run_id, pass an absolute root. Prefer "
    "this narrower tool instead of list_findings when you only need "
    "dead-code findings."
)

GENERATE_PR_SUMMARY: Final = (
    "Generate a PR-friendly CodeClone summary for changed files. Prefer "
    "format='markdown' for compact LLM-facing output; use 'json' only "
    "for machine post-processing."
)

MARK_FINDING_REVIEWED: Final = (
    "Mark finding reviewed in this MCP session only; cleared on "
    "process restart or clear_session_runs."
)

LIST_REVIEWED_FINDINGS: Final = (
    "List in-memory reviewed findings for the current or specified run."
)

START_CONTROLLED_CHANGE: Final = (
    "Pre-edit workflow: check workspace for concurrent intents, "
    "declare change intent with scope, compute blast radius "
    "(direct + bounded transitive for high-radius changes), and "
    "return patch budget — all in one call. Requires an existing "
    "analysis run for the given root; call analyze_repository "
    "first if needed. Returns intent_id for finish_controlled_change. "
    "Use dirty_scope_policy=continue_own_wip to resume known "
    "uncommitted work in declared scope when no foreign dirty overlap "
    "exists; finish must still prove scope via changed_files or diff_ref. "
    "Does not run analysis implicitly."
)

FINISH_CONTROLLED_CHANGE: Final = (
    "Post-edit pipeline: hygiene, scope check, verify, patch_trail, optional "
    "claims, receipt, clear. Pass after_run_id when "
    "verification.after_run_required. Use detail_level=full for hygiene path "
    "attribution; patch_trail_detail summary|full. Set propose_memory=true "
    "for draft memory candidates on accept."
)

MANAGE_CHANGE_INTENT: Final = (
    "Manage the agent change intent lifecycle for the current MCP "
    "session and optional workspace registry. Actions: 'list_workspace' "
    "to inspect concurrent workspace intents, 'declare' to declare "
    "intended scope before editing, 'get' to retrieve active intent, "
    "'check' to verify actual diff against declared scope, 'promote' to "
    "activate a queued intent, 'clear' to remove intent, 'renew' to "
    "refresh the active lease before long edits or test runs, "
    "'gc_workspace' to clean stale registry files, 'recover' to "
    "explicitly reclaim a recoverable intent, and 'reset_workspace' for "
    "interrupted-session recovery. In-memory intent state remains "
    "session-local; workspace coordination state is ephemeral under "
    ".codeclone/intents/."
)

CLEAR_SESSION_RUNS: Final = (
    "Clear all in-memory MCP analysis runs and ephemeral session state "
    "for this server process."
)

GET_WORKSPACE_SESSION_STATS: Final = (
    "IDE-only workspace session dashboard: active agents, change intents, "
    "lease health, latest cached run summary, and audit token footprint. "
    "Mirrors CLI --session-stats. Registered only when the MCP server is "
    "launched with --ide-governance-channel (CodeClone VS Code). Not exposed "
    "to agent clients on the default launcher."
)

GET_CONTROLLER_AUDIT_TRAIL: Final = (
    "IDE-only controller audit trail summary with recent events and optional "
    "payload token footprint. Mirrors CLI --audit and requires "
    "audit_enabled=true. Registered only with --ide-governance-channel. "
    "Not for agent MCP clients."
)

TITLE_ANALYZE_REPOSITORY: Final = "Analyze Repository"
TITLE_ANALYZE_CHANGED_PATHS: Final = "Analyze Changed Paths"
TITLE_GET_RUN_SUMMARY: Final = "Get Run Summary"
TITLE_GET_PRODUCTION_TRIAGE: Final = "Get Production Triage"
TITLE_GET_BLAST_RADIUS: Final = "Get Blast Radius"
TITLE_GET_BLAST_ARTIFACT: Final = "Get Blast Artifact"
TITLE_GET_IMPLEMENTATION_CONTEXT: Final = "Get Implementation Context"
TITLE_GET_RELEVANT_MEMORY: Final = "Get Relevant Memory"
TITLE_GET_MEMORY_PROJECTION_PAGE: Final = "Get Memory Projection Page"
TITLE_QUERY_ENGINEERING_MEMORY: Final = "Query Engineering Memory"
TITLE_MANAGE_ENGINEERING_MEMORY: Final = "Manage Engineering Memory"
TITLE_CHECK_PATCH_CONTRACT: Final = "Check Patch Contract"
TITLE_CREATE_REVIEW_RECEIPT: Final = "Create Review Receipt"
TITLE_GET_REVIEW_RECEIPT: Final = "Get Review Receipt"
TITLE_GET_PATCH_TRAIL: Final = "Get Patch Trail"
TITLE_VALIDATE_REVIEW_CLAIMS: Final = "Validate Review Claims"
TITLE_HELP: Final = "Help"
TITLE_QUERY_PLATFORM_OBSERVABILITY: Final = "Query Platform Observability"
TITLE_EVALUATE_GATES: Final = "Evaluate Gates"
TITLE_GET_REPORT_SECTION: Final = "Get Report Section"
TITLE_LIST_FINDINGS: Final = "List Findings"
TITLE_GET_FINDING: Final = "Get Finding"
TITLE_GET_REMEDIATION: Final = "Get Remediation"
TITLE_LIST_HOTSPOTS: Final = "List Hotspots"
TITLE_COMPARE_RUNS: Final = "Compare Runs"
TITLE_CHECK_COMPLEXITY: Final = "Check Complexity"
TITLE_CHECK_CLONES: Final = "Check Clones"
TITLE_CHECK_COUPLING: Final = "Check Coupling"
TITLE_CHECK_COHESION: Final = "Check Cohesion"
TITLE_CHECK_DEAD_CODE: Final = "Check Dead Code"
TITLE_GENERATE_PR_SUMMARY: Final = "Generate PR Summary"
TITLE_MARK_FINDING_REVIEWED: Final = "Mark Finding Reviewed"
TITLE_LIST_REVIEWED_FINDINGS: Final = "List Reviewed Findings"
TITLE_START_CONTROLLED_CHANGE: Final = "Start Controlled Change"
TITLE_FINISH_CONTROLLED_CHANGE: Final = "Finish Controlled Change"
TITLE_MANAGE_CHANGE_INTENT: Final = "Manage Change Intent"
TITLE_CLEAR_SESSION_RUNS: Final = "Clear Session Runs"
TITLE_GET_WORKSPACE_SESSION_STATS: Final = "Get Workspace Session Stats"
TITLE_GET_CONTROLLER_AUDIT_TRAIL: Final = "Get Controller Audit Trail"
