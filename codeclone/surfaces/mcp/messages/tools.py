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

VALIDATE_REVIEW_CLAIMS: Final = (
    "Validate cited review text against canonical report semantics. "
    "Detects deterministic mischaracterizations: Security Surfaces "
    "called vulnerabilities, report-only signals called CI failures, "
    "known baseline debt called new regressions, dead code claimed "
    "where runtime reachability evidence exists, and fixes claimed "
    "without post-patch verification. Structural citation matching; "
    "not NLP."
)

HELP: Final = (
    "Bounded workflow/contract guidance with doc links. compact "
    "includes anti_patterns; normal adds warnings. Topics include "
    "workflow, change_control, trust_boundaries."
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
    "Does not run analysis implicitly."
)

FINISH_CONTROLLED_CHANGE: Final = (
    "Post-edit verify, receipt, and intent clear. Pass after_run_id "
    "when verification.verification_profile requires it. Read "
    "verification.verification_profile for applied checks."
)

MANAGE_CHANGE_INTENT: Final = (
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
)

CLEAR_SESSION_RUNS: Final = (
    "Clear all in-memory MCP analysis runs and ephemeral session state "
    "for this server process."
)

TITLE_ANALYZE_REPOSITORY: Final = "Analyze Repository"
TITLE_ANALYZE_CHANGED_PATHS: Final = "Analyze Changed Paths"
TITLE_GET_RUN_SUMMARY: Final = "Get Run Summary"
TITLE_GET_PRODUCTION_TRIAGE: Final = "Get Production Triage"
TITLE_GET_BLAST_RADIUS: Final = "Get Blast Radius"
TITLE_CHECK_PATCH_CONTRACT: Final = "Check Patch Contract"
TITLE_CREATE_REVIEW_RECEIPT: Final = "Create Review Receipt"
TITLE_VALIDATE_REVIEW_CLAIMS: Final = "Validate Review Claims"
TITLE_HELP: Final = "Help"
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
