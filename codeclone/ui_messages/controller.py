# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Controller query-mode screen copy."""

from __future__ import annotations

from typing import Final

# ── workflow flag validation ─────────────────────────────────────────

ERR_STRICTNESS_PATCH_VERIFY_ONLY: Final = (
    "--strictness is only valid with --patch-verify."
)
ERR_SESSION_STATS_COMBINED: Final = (
    "--session-stats cannot be combined with "
    "--audit, --blast-radius, or --patch-verify."
)
ERR_AUDIT_COMBINED: Final = (
    "--audit cannot be combined with --blast-radius or --patch-verify."
)
ERR_BLAST_PATCH_BOTH: Final = "Use --blast-radius or --patch-verify, not both."
ERR_CONTROLLER_NO_BASELINE_UPDATE: Final = (
    "Controller query modes cannot update baselines."
)
ERR_CONTROLLER_NO_CHANGED_SCOPE: Final = (
    "Controller query modes cannot be combined with changed-scope flags."
)
ERR_CONTROLLER_TERMINAL_ONLY: Final = (
    "Controller query modes are terminal-only and cannot be combined "
    "with report output flags."
)

# ── metrics baseline ────────────────────────────────────────────────

ERR_METRICS_BASELINE_REQUIRES_ANALYSIS: Final = (
    "Metrics baseline operations require metrics analysis. Remove --skip-metrics."
)
ERR_METRICS_BASELINE_REQUIRED_FOR_GATES: Final = (
    "Metrics baseline file is required for metrics baseline-aware gates. "
    "Run codeclone . --update-metrics-baseline first."
)
ERR_METRICS_BASELINE_UPDATE_WITHOUT_METRICS: Final = (
    "Cannot update metrics baseline: metrics were not computed."
)
ERR_METRICS_BASELINE_TYPING_GATES: Final = (
    "Typing/docstring regression gates require a metrics baseline that includes "
    "coverage adoption data. Run codeclone . --update-metrics-baseline first."
)
ERR_METRICS_BASELINE_API_GATES: Final = (
    "API break gating requires a metrics baseline with public API surface data. "
    "Run codeclone . --api-surface --update-metrics-baseline first."
)

# ── session stats ───────────────────────────────────────────────────

SESSION_STATS_READ_FAILED: Final = "failed to read session state: {error}"
SESSION_STATS_TITLE: Final = "Session Stats"
SESSION_STATS_WORKSPACE: Final = "Workspace:"
SESSION_STATS_INTENT_REGISTRY: Final = "Intent registry:"
SESSION_STATS_AUDIT: Final = "Audit trail:"
SESSION_STATS_AUDIT_ENABLED: Final = "enabled"
SESSION_STATS_LATEST_RUN: Final = "Latest run:"
SESSION_STATS_LATEST_RUN_NONE: Final = "none"
SESSION_STATS_LATEST_RUN_SOURCE_DISK: Final = "persisted report (CLI)"
SESSION_STATS_LATEST_RUN_SOURCE_AUDIT_MCP: Final = "MCP session (audit)"
SESSION_STATS_LATEST_RUN_SOURCE_AUDIT_CLI: Final = "CLI run (audit)"
SESSION_STATS_CACHE: Final = "Cache:"
SESSION_STATS_LIVE_AGENTS: Final = "Live agents:"
SESSION_STATS_ACTIVE_INTENTS: Final = "Active edit intents:"
SESSION_STATS_VISIBLE_INTENTS: Final = "Visible intent records:"
SESSION_STATS_STALE: Final = "Stale intents:"
SESSION_STATS_EXPIRED: Final = "Expired intents:"
SESSION_STATS_RECOVERABLE: Final = "Recoverable:"
SESSION_STATS_WORKSPACE_HEALTH: Final = "Workspace health:"
SESSION_STATS_NO_AGENTS: Final = "No live workspace agents found."
SESSION_STATS_REPORT_PRESENT: Final = "report.json present ({files} files)"
SESSION_STATS_RETENTION_FOOTPRINT: Final = "Retention payload footprint"
SESSION_STATS_RETENTION_FOOTPRINT_VERBOSE: Final = (
    "Retention payload footprint: ~{tokens:,} tokens in retention window "
    "({encoding}, {calls} tool calls)"
)
SESSION_STATS_TOP_WORKFLOWS: Final = "Top payload workflows"
SESSION_STATS_WORKSPACE_INTENT_RECORDS_TITLE: Final = "Workspace intent records"
AUDIT_NOT_ENABLED: Final = "audit is not enabled."

# ── audit trail ─────────────────────────────────────────────────────

AUDIT_TITLE: Final = "Controller Audit Trail"
AUDIT_DATABASE: Final = "Database:"
AUDIT_RETENTION: Final = "Retention:"
AUDIT_OLDEST: Final = "Oldest event:"
AUDIT_LATEST: Final = "Latest event:"
AUDIT_SUMMARY: Final = "Summary:"
AUDIT_VIOLATIONS: Final = "Violations:"
AUDIT_MCP_FOOTPRINT_PANEL: Final = "MCP Payload Footprint"
AUDIT_TOKENS_BY_TYPE: Final = "Tokens by Type"
AUDIT_TOP_WORKFLOWS: Final = "Top Workflows"
AUDIT_TOP_PAYLOADS: Final = "Top Payloads"
AUDIT_PAYLOAD_BUDGET_WARNINGS: Final = "Payload Budget Warnings"
AUDIT_MCP_PAYLOAD_FOOTPRINT_ROW: Final = "MCP payload footprint"
AUDIT_NONE: Final = "none"
AUDIT_COL_WORKFLOW: Final = "Workflow"
AUDIT_COL_TOKENS: Final = "Tokens"
AUDIT_COL_TIME: Final = "Time"
AUDIT_COL_TYPE: Final = "Type"
AUDIT_COL_SEVERITY: Final = "Severity"
AUDIT_COL_INTENT: Final = "Intent"
AUDIT_COL_STATUS: Final = "Status"
AUDIT_COL_RUN: Final = "Run"
AUDIT_COL_AGENT: Final = "Agent"
AUDIT_COL_FIRST: Final = "First"
AUDIT_COL_LAST: Final = "Last"
AUDIT_STAT_TOTAL_TOKENS: Final = "Retention window total"
AUDIT_STAT_TOOL_CALLS: Final = "Retention window calls"
AUDIT_STAT_AVG_TOKENS: Final = "Avg tokens/call"
AUDIT_STAT_P95_TOKENS: Final = "p95 tokens"
AUDIT_STAT_MAX_TOKENS: Final = "Max tokens"
AUDIT_STAT_ENCODING: Final = "Encoding"
AUDIT_BREAKDOWN_COL_CALLS: Final = "Calls"
AUDIT_BREAKDOWN_COL_TOTAL: Final = "Total"
AUDIT_BREAKDOWN_COL_MAX: Final = "Max"
AUDIT_TOP_COL_RANK: Final = "#"
AUDIT_FIELD_EMPTY: Final = "-"
AUDIT_TOKENS_EMPTY: Final = "—"
AUDIT_QUIET_PREFIX: Final = "audit:"
AUDIT_QUIET_TEMPLATE: Final = (
    "{prefix} {total_events} events | "
    "intents={intent_events} contracts={contract_events} "
    "receipts={receipt_events} violations={violation_events} "
    "last={last_relative}"
)
AUDIT_EVENT_TYPE_ALIASES: Final[dict[str, str]] = {
    "intent.declared": "decl",
    "intent.checked": "check",
    "intent.expanded": "expand",
    "intent.violated": "intent!",
    "intent.cleared": "clear",
    "intent.renewed": "renew",
    "blast_radius.computed": "radius",
    "patch_budget.computed": "budget",
    "patch_contract.verified": "verify",
    "patch_contract.violated": "verify!",
    "patch_contract.expired": "expired",
    "claim_validation.completed": "claims",
    "claim_validation.violated": "claims!",
    "review_receipt.created": "receipt",
    "baseline_abuse.detected": "baseline!",
    "workspace.conflict_detected": "conflict",
    "workspace.gc_completed": "gc",
}
AUDIT_BUDGET_WORKFLOW_HEAVY: Final = (
    "Workflow {workflow} totals {total_tokens:,} tokens, above "
    "{threshold:,} threshold (heavy)"
)
AUDIT_BUDGET_WORKFLOW_WATCH: Final = (
    "Workflow {workflow} totals {total_tokens:,} tokens, above "
    "{threshold:,} threshold (watch)"
)
AUDIT_BUDGET_PAYLOAD_HEAVY: Final = (
    "{event_type} payload {estimated_tokens:,} tokens (heavy)"
)
AUDIT_RELATIVE_NONE: Final = "none"

# ── session stats ───────────────────────────────────────────────────

SESSION_STATS_QUIET_PREFIX: Final = "session-stats:"
SESSION_STATS_QUIET_TEMPLATE: Final = (
    "{prefix} {workspace_health} | live_agents={live_agents} "
    "active_intents={active_intents} visible_intents={visible_intents} "
    "stale={stale} latest_run={latest_run}"
)
SESSION_STATS_QUIET_HEALTH: Final = "health={health}"
SESSION_STATS_COL_PID: Final = "PID"
SESSION_STATS_COL_AGENT: Final = "Agent"
SESSION_STATS_COL_OWNERSHIP: Final = "Ownership"
SESSION_STATS_COL_STATUS: Final = "Status"
SESSION_STATS_COL_SCOPE: Final = "Scope"
SESSION_STATS_COL_LEASE: Final = "Lease"
SESSION_STATS_COL_FILES: Final = "Files"
SESSION_STATS_COL_WORKFLOW: Final = "Workflow"
SESSION_STATS_COL_TOKENS: Final = "Tokens"
SESSION_STATS_COL_CALLS: Final = "Calls"
SESSION_STATS_AGENT_UNKNOWN: Final = "unknown"
SESSION_STATS_ALLOWED_PREFIX: Final = "allowed:"
SESSION_STATS_LEASE_REMAINING: Final = "lease: {lease} remaining"
SESSION_STATS_SCOPE_FILE: Final = "file"
SESSION_STATS_SCOPE_FILES: Final = "files"

# ── patch verify ────────────────────────────────────────────────────

PATCH_VERIFY_LABEL_STRICTNESS: Final = "Strictness:"
PATCH_VERIFY_LABEL_STATUS: Final = "Status:"
PATCH_VERIFY_LABEL_HEALTH: Final = "Health:"
PATCH_VERIFY_LABEL_STRUCTURAL_DELTA: Final = "Structural delta:"
PATCH_VERIFY_LABEL_REGRESSIONS: Final = "Regressions:"
PATCH_VERIFY_LABEL_IMPROVEMENTS: Final = "Improvements:"
PATCH_VERIFY_LABEL_VERDICT: Final = "Verdict:"
PATCH_VERIFY_LABEL_GATE_PREVIEW: Final = "Gate preview:"
PATCH_VERIFY_GATE_EXIT: Final = "(exit {exit_code})"
PATCH_VERIFY_CONTRACT_VIOLATIONS: Final = "Contract violations"
PATCH_VERIFY_VERDICT_REGRESSED: Final = "regressed"
PATCH_VERIFY_VERDICT_STABLE: Final = "stable"
PATCH_VERIFY_ACCEPTED: Final = "Patch contract accepted."
PATCH_VERIFY_VIOLATED: Final = "Patch contract violated."
PATCH_VERIFY_RELAXED_ADVISORY: Final = (
    "Patch contract has advisory violations but relaxed mode exits 0."
)

# ── blast radius ────────────────────────────────────────────────────

BLAST_RADIUS_FILES: Final = "Files:"
BLAST_RADIUS_RISK_LEVEL: Final = "Risk level:"
BLAST_RADIUS_DIRECT_DEPENDENTS: Final = "Direct dependents"
BLAST_RADIUS_CLONE_COHORT: Final = "Clone cohort members"
BLAST_RADIUS_DEPENDENCY_CYCLES: Final = "Dependency cycles"
BLAST_RADIUS_DO_NOT_TOUCH: Final = "Do not touch"
BLAST_RADIUS_REVIEW_CONTEXT: Final = "Review context"
BLAST_RADIUS_GUARDRAILS: Final = "Guardrails:"
BLAST_RADIUS_NONE: Final = "none"
BLAST_RADIUS_MORE: Final = "... and {count} more"
BLAST_RADIUS_REQUIRES_REPORT: Final = (
    "Blast radius requires a canonical report document."
)
BLAST_RADIUS_INVALID_SELECTION: Final = (
    "Invalid --blast-radius path selection:\n{rendered}"
)
BLAST_RADIUS_SKIPPED_INVENTORY: Final = (
    "Blast radius skipped files outside analysis inventory: {rendered}"
)
BLAST_RADIUS_REQUIRES_INVENTORY_FILE: Final = (
    "--blast-radius requires at least one file from the analysis inventory."
)
