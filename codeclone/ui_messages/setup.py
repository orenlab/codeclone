# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Human copy for ``codeclone setup`` readiness projection."""

from __future__ import annotations

from typing import Final

SETUP_STATUS_TITLE: Final = "CodeClone setup readiness"
SETUP_DOCTOR_TITLE: Final = "CodeClone setup doctor"
SETUP_PLAN_TITLE: Final = "CodeClone setup plan"
SETUP_PLAN_EMPTY: Final = "No configuration changes recommended."
SETUP_PLAN_BLOCKED: Final = (
    "Plan blocked until pyproject.toml validation issues are resolved."
)
SETUP_PLAN_READ_ONLY_NOTE: Final = "Read-only preview — no files were modified."
SETUP_APPLY_TITLE: Final = "CodeClone setup apply"
SETUP_APPLY_NOOP: Final = "No plan actions were applied."
SETUP_APPLY_BLOCKED: Final = "Apply blocked — fix plan blockers and re-run setup plan."
SETUP_APPLY_CONFIRM_REQUIRED: Final = (
    "Refusing to modify files without confirmation. Re-run with --yes to apply "
    "non-interactively, or use --dry-run to preview changes."
)
SETUP_APPLY_CONFIRM_PROMPT: Final = "Apply these configuration changes?"
SETUP_APPLY_ABORTED: Final = "Apply aborted — no files were modified."
SETUP_APPLY_STALE_PLAN: Final = (
    "Repository changed since the plan was computed. Re-run `codeclone setup plan` "
    "and apply again."
)
SETUP_DRY_RUN_ONLY_APPLY: Final = "--dry-run is only valid for `codeclone setup apply`."
SETUP_YES_ONLY_APPLY: Final = "--yes is only valid for `codeclone setup apply`."
SETUP_PLAN_ID_ONLY_APPLY: Final = "--plan-id is only valid for `codeclone setup apply`."
SETUP_WIZARD_JSON_UNSUPPORTED: Final = (
    "The interactive wizard has no --json output; use `setup --json` or "
    "`setup plan --json`."
)
SETUP_WIZARD_TITLE: Final = "CodeClone setup wizard"
SETUP_WIZARD_HUB_RULE: Final = "Capability hub"
SETUP_WIZARD_SPHERE_RULE: Final = "capability sphere"
SETUP_WIZARD_PROMPT: Final = "Select hub item"
SETUP_WIZARD_GUIDED_LABEL: Final = "Guided setup"
SETUP_WIZARD_GUIDED_HINT: Final = "Plan → confirm → apply → refresh readiness"
SETUP_WIZARD_DOCTOR_LABEL: Final = "Doctor"
SETUP_WIZARD_DOCTOR_HINT: Final = "Verbose probe diagnostics"
SETUP_WIZARD_QUIT_LABEL: Final = "Quit"
SETUP_WIZARD_QUIT_HINT: Final = "Exit the wizard"
SETUP_WIZARD_CONFIRM_APPLY: Final = "Apply the recommended configuration changes?"
SETUP_WIZARD_APPLY_SKIPPED: Final = "Apply skipped — no files were modified."
SETUP_WIZARD_GUIDED_BLOCKED: Final = (
    "Guided setup blocked until pyproject.toml validation issues are resolved."
)
SETUP_WIZARD_GUIDED_EMPTY: Final = "Guided setup found no changes to apply."
SETUP_WIZARD_UPDATED_READINESS: Final = "Updated readiness after apply:"
SETUP_WIZARD_SPHERE_EMPTY: Final = "No capabilities in this sphere."
SETUP_WIZARD_TTY_REQUIRED: Final = (
    "Interactive setup wizard requires a TTY. "
    "Use `codeclone setup plan` and `codeclone setup apply` instead."
)
SETUP_WIZARD_RICH_REQUIRED: Final = (
    "Interactive setup wizard requires Rich console output."
)

GROUP_LABELS: Final[dict[str, str]] = {
    "core_analysis": "Core analysis",
    "governed_agent_workflows": "Governed agent workflows",
    "project_knowledge": "Project knowledge",
    "team_and_release": "Team & release",
}

CAPABILITY_LABELS: Final[dict[str, str]] = {
    "analysis": "Repository analysis",
    "baseline": "Baseline & trust",
    "reports": "Reports",
    "mcp_runtime": "MCP runtime",
    "controlled_change": "Controlled changes",
    "audit_and_intents": "Audit & intents",
    "engineering_memory": "Engineering Memory",
    "semantic_retrieval": "Semantic retrieval",
    "coverage_evidence": "Coverage evidence",
    "analytics_cockpit": "Cockpit / analytics",
    "ci_policy": "CI policy",
    "github_workflow": "GitHub workflow",
    "pre_commit_hook": "pre-commit hook",
    "workspace_hygiene": "Workspace hygiene",
}

MCP_INSTALL_HINT: Final = (
    "CodeClone MCP support requires the optional 'mcp' extra. "
    "Install it with: pip install 'codeclone[mcp]'"
)

MCP_UV_INSTALL_HINT: Final = (
    'uv tool install "codeclone[mcp]" then configure MCP in your client'
)

MCP_CONFIGURE_CLIENT_HINT: Final = (
    "Configure and start the CodeClone MCP server in your IDE or agent client."
)

ACTION_FIX_PYPROJECT: Final = "Fix the tool.codeclone entries in pyproject.toml."

READINESS_LABELS: Final[dict[str, str]] = {
    "ready": "ready",
    "attention": "attention",
    "blocked": "blocked",
    "optional": "optional",
    "not_applicable": "n/a",
}

AVAILABILITY_LABELS: Final[dict[str, str]] = {
    "built_in": "built-in",
    "optional_extra": "extra",
    "external_tool": "external",
    "unsupported": "n/a",
}

SETUP_STATUS_BASE_LABEL: Final = "Base"
SETUP_DOCTOR_PROBES_HEADER: Final = "Probe diagnostics"
SETUP_DOCTOR_PROBES_LABEL: Final = "probes/paths checked"

REASON_REQUIRES_MCP_EXTRA: Final = "Requires codeclone[mcp]"
REASON_MCP_INSTALLED_NOT_VERIFIED: Final = (
    "MCP extra is installed; configure and verify your MCP client connection"
)
REASON_CONTROLLED_CHANGE_NO_CLIENT: Final = (
    "MCP runtime is available but no supported client MCP config was found"
)
REASON_AUDIT_DISABLED: Final = "Audit trail is disabled in pyproject configuration"
REASON_AUDIT_DB_MISSING: Final = (
    "Audit is enabled but the audit database does not exist yet"
)
REASON_AUDIT_EMPTY: Final = "Audit database exists but has recorded no events yet"
REASON_AUDIT_READY: Final = ""
REASON_BASELINE_MISSING: Final = "Baseline file is missing or not configured"
REASON_BASELINE_UNTRUSTED: Final = "Baseline exists but is not trusted for gating"
REASON_BASELINE_CORRUPT: Final = (
    "Baseline file is corrupt or has an incompatible schema"
)
REASON_BASELINE_UNREADABLE: Final = "Baseline file exists but could not be read"
REASON_ANALYSIS_CORE_MISSING: Final = "CodeClone core package could not be resolved"
REASON_ANALYSIS_INVALID_CONFIG: Final = (
    "Invalid tool.codeclone configuration in pyproject.toml"
)
REASON_ANALYSIS_UNCONFIGURED: Final = "No [tool.codeclone] section in pyproject.toml"
REASON_MEMORY_EMPTY: Final = "Engineering Memory store exists but has no records yet"
REASON_MEMORY_MISSING: Final = "Engineering Memory store has not been created yet"
REASON_SEMANTIC_OPTIONAL: Final = "Requires semantic optional extras"
REASON_SEMANTIC_NO_STORE: Final = (
    "Semantic packages installed but no Engineering Memory store to index"
)
REASON_SEMANTIC_DISABLED: Final = (
    "Semantic packages installed but semantic memory is not enabled in configuration"
)
REASON_COVERAGE_OPTIONAL: Final = "Requires codeclone[coverage-xml]"
REASON_ANALYTICS_OPTIONAL: Final = "Requires codeclone[analytics]"
REASON_CI_NOT_ENABLED: Final = (
    "CI gating is optional and is not currently enabled in configuration"
)
REASON_CI_BASELINE_ATTENTION: Final = (
    "CI-like gates are enabled but baseline trust or metrics section needs attention"
)
REASON_GITHUB_WORKFLOW_MISSING: Final = (
    "No GitHub Actions workflow referencing CodeClone found"
)
REASON_GITHUB_WORKFLOW_UNREADABLE: Final = (
    "A GitHub Actions workflow file could not be read"
)
REASON_PRE_COMMIT_MISSING: Final = "No pre-commit hook referencing CodeClone found"
REASON_PRE_COMMIT_UNREADABLE: Final = ".pre-commit-config.yaml could not be read"
REASON_WORKSPACE_HYGIENE: Final = (
    ".gitignore does not cover .codeclone/ workspace artifacts"
)
REASON_UNKNOWN_PROBE: Final = (
    "Probe state is ambiguous; re-run setup after fixing paths"
)
REASON_ATTENTION_GENERIC: Final = "Capability needs attention; see doctor for details"
REASON_NOT_APPLICABLE: Final = "Not applicable on this platform"
REASON_OPTIONAL_EXTRA_MISSING: Final = (
    "Optional capability is not installed in this environment"
)

MATURITY_CONNECTED: Final = "connected"
MATURITY_GOVERNED: Final = "governed"
MATURITY_EVIDENCE: Final = "evidence_backed"
MATURITY_TEAM: Final = "team_ready"
MATURITY_RELEASE: Final = "release_ready"

__all__ = [
    "ACTION_FIX_PYPROJECT",
    "AVAILABILITY_LABELS",
    "CAPABILITY_LABELS",
    "GROUP_LABELS",
    "MATURITY_CONNECTED",
    "MATURITY_EVIDENCE",
    "MATURITY_GOVERNED",
    "MATURITY_RELEASE",
    "MATURITY_TEAM",
    "MCP_CONFIGURE_CLIENT_HINT",
    "MCP_INSTALL_HINT",
    "MCP_UV_INSTALL_HINT",
    "READINESS_LABELS",
    "REASON_ANALYSIS_CORE_MISSING",
    "REASON_ANALYSIS_INVALID_CONFIG",
    "REASON_ANALYSIS_UNCONFIGURED",
    "REASON_ANALYTICS_OPTIONAL",
    "REASON_ATTENTION_GENERIC",
    "REASON_AUDIT_DB_MISSING",
    "REASON_AUDIT_DISABLED",
    "REASON_AUDIT_EMPTY",
    "REASON_AUDIT_READY",
    "REASON_BASELINE_CORRUPT",
    "REASON_BASELINE_MISSING",
    "REASON_BASELINE_UNREADABLE",
    "REASON_BASELINE_UNTRUSTED",
    "REASON_CI_BASELINE_ATTENTION",
    "REASON_CI_NOT_ENABLED",
    "REASON_CONTROLLED_CHANGE_NO_CLIENT",
    "REASON_COVERAGE_OPTIONAL",
    "REASON_GITHUB_WORKFLOW_MISSING",
    "REASON_GITHUB_WORKFLOW_UNREADABLE",
    "REASON_MCP_INSTALLED_NOT_VERIFIED",
    "REASON_MEMORY_EMPTY",
    "REASON_MEMORY_MISSING",
    "REASON_NOT_APPLICABLE",
    "REASON_OPTIONAL_EXTRA_MISSING",
    "REASON_PRE_COMMIT_MISSING",
    "REASON_PRE_COMMIT_UNREADABLE",
    "REASON_REQUIRES_MCP_EXTRA",
    "REASON_SEMANTIC_DISABLED",
    "REASON_SEMANTIC_NO_STORE",
    "REASON_SEMANTIC_OPTIONAL",
    "REASON_UNKNOWN_PROBE",
    "REASON_WORKSPACE_HYGIENE",
    "SETUP_APPLY_ABORTED",
    "SETUP_APPLY_BLOCKED",
    "SETUP_APPLY_CONFIRM_PROMPT",
    "SETUP_APPLY_CONFIRM_REQUIRED",
    "SETUP_APPLY_NOOP",
    "SETUP_APPLY_STALE_PLAN",
    "SETUP_APPLY_TITLE",
    "SETUP_DOCTOR_PROBES_HEADER",
    "SETUP_DOCTOR_PROBES_LABEL",
    "SETUP_DOCTOR_TITLE",
    "SETUP_DRY_RUN_ONLY_APPLY",
    "SETUP_PLAN_BLOCKED",
    "SETUP_PLAN_EMPTY",
    "SETUP_PLAN_ID_ONLY_APPLY",
    "SETUP_PLAN_READ_ONLY_NOTE",
    "SETUP_PLAN_TITLE",
    "SETUP_STATUS_BASE_LABEL",
    "SETUP_STATUS_TITLE",
    "SETUP_WIZARD_APPLY_SKIPPED",
    "SETUP_WIZARD_CONFIRM_APPLY",
    "SETUP_WIZARD_DOCTOR_HINT",
    "SETUP_WIZARD_DOCTOR_LABEL",
    "SETUP_WIZARD_GUIDED_BLOCKED",
    "SETUP_WIZARD_GUIDED_EMPTY",
    "SETUP_WIZARD_GUIDED_HINT",
    "SETUP_WIZARD_GUIDED_LABEL",
    "SETUP_WIZARD_HUB_RULE",
    "SETUP_WIZARD_JSON_UNSUPPORTED",
    "SETUP_WIZARD_PROMPT",
    "SETUP_WIZARD_QUIT_HINT",
    "SETUP_WIZARD_QUIT_LABEL",
    "SETUP_WIZARD_RICH_REQUIRED",
    "SETUP_WIZARD_SPHERE_EMPTY",
    "SETUP_WIZARD_SPHERE_RULE",
    "SETUP_WIZARD_TITLE",
    "SETUP_WIZARD_TTY_REQUIRED",
    "SETUP_WIZARD_UPDATED_READINESS",
    "SETUP_YES_ONLY_APPLY",
]
