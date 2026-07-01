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

READINESS_LABELS: Final[dict[str, str]] = {
    "ready": "ready",
    "attention": "attention",
    "blocked": "blocked",
    "optional": "optional",
    "not_applicable": "n/a",
}

REASON_REQUIRES_MCP_EXTRA: Final = "Requires codeclone[mcp]"
REASON_MCP_INSTALLED_NOT_VERIFIED: Final = (
    "MCP extra is installed; configure and verify your MCP client connection"
)
REASON_CONTROLLED_CHANGE_OPTIONAL: Final = REASON_REQUIRES_MCP_EXTRA
REASON_CONTROLLED_CHANGE_NO_CLIENT: Final = (
    "MCP runtime is available but no supported client MCP config was found"
)
REASON_CONTROLLED_CHANGE_ATTENTION: Final = (
    "Configure MCP in your IDE or agent client to enable controlled changes"
)
REASON_AUDIT_DISABLED: Final = "Audit trail is disabled in pyproject configuration"
REASON_AUDIT_DB_MISSING: Final = "Audit database path is missing or unreadable"
REASON_AUDIT_CONFIGURED: Final = (
    "History readable; intents are created via MCP controlled changes"
)
REASON_BASELINE_MISSING: Final = "Baseline file is missing or not configured"
REASON_BASELINE_UNTRUSTED: Final = "Baseline exists but is not trusted for gating"
REASON_BASELINE_READY: Final = ""
REASON_ANALYSIS_INVALID_CONFIG: Final = (
    "Invalid tool.codeclone configuration in pyproject.toml"
)
REASON_ANALYSIS_UNCONFIGURED: Final = "No [tool.codeclone] section in pyproject.toml"
REASON_ANALYSIS_READY: Final = ""
REASON_MEMORY_EMPTY: Final = "Engineering Memory store is missing or empty"
REASON_MEMORY_READY: Final = ""
REASON_SEMANTIC_OPTIONAL: Final = "Requires semantic optional extras"
REASON_COVERAGE_OPTIONAL: Final = "Requires codeclone[coverage-xml]"
REASON_ANALYTICS_OPTIONAL: Final = "Requires codeclone[analytics]"
REASON_CI_BASELINE_ATTENTION: Final = (
    "CI-like gates are enabled but baseline trust or metrics section needs attention"
)
REASON_CI_READY: Final = ""
REASON_GITHUB_WORKFLOW_MISSING: Final = (
    "No GitHub Actions workflow referencing CodeClone found"
)
REASON_PRE_COMMIT_MISSING: Final = "No pre-commit hook referencing CodeClone found"
REASON_WORKSPACE_HYGIENE: Final = (
    ".gitignore does not cover .codeclone/ workspace artifacts"
)
REASON_WORKSPACE_HYGIENE_READY: Final = ""
REASON_REPORTS_READY: Final = ""
REASON_UNKNOWN_PROBE: Final = (
    "Probe state is ambiguous; re-run setup after fixing paths"
)
REASON_OPTIONAL_EXTRA_MISSING: Final = (
    "Optional capability is not installed in this environment"
)

MATURITY_CONNECTED: Final = "connected"
MATURITY_GOVERNED: Final = "governed"
MATURITY_EVIDENCE: Final = "evidence_backed"
MATURITY_TEAM: Final = "team_ready"
MATURITY_RELEASE: Final = "release_ready"

__all__ = [
    "CAPABILITY_LABELS",
    "GROUP_LABELS",
    "MATURITY_CONNECTED",
    "MATURITY_EVIDENCE",
    "MATURITY_GOVERNED",
    "MATURITY_RELEASE",
    "MATURITY_TEAM",
    "MCP_INSTALL_HINT",
    "MCP_UV_INSTALL_HINT",
    "READINESS_LABELS",
    "REASON_ANALYSIS_INVALID_CONFIG",
    "REASON_ANALYSIS_READY",
    "REASON_ANALYSIS_UNCONFIGURED",
    "REASON_ANALYTICS_OPTIONAL",
    "REASON_AUDIT_CONFIGURED",
    "REASON_AUDIT_DB_MISSING",
    "REASON_AUDIT_DISABLED",
    "REASON_BASELINE_MISSING",
    "REASON_BASELINE_READY",
    "REASON_BASELINE_UNTRUSTED",
    "REASON_CI_BASELINE_ATTENTION",
    "REASON_CI_READY",
    "REASON_CONTROLLED_CHANGE_ATTENTION",
    "REASON_CONTROLLED_CHANGE_NO_CLIENT",
    "REASON_CONTROLLED_CHANGE_OPTIONAL",
    "REASON_COVERAGE_OPTIONAL",
    "REASON_GITHUB_WORKFLOW_MISSING",
    "REASON_MCP_INSTALLED_NOT_VERIFIED",
    "REASON_MEMORY_EMPTY",
    "REASON_MEMORY_READY",
    "REASON_OPTIONAL_EXTRA_MISSING",
    "REASON_PRE_COMMIT_MISSING",
    "REASON_REPORTS_READY",
    "REASON_REQUIRES_MCP_EXTRA",
    "REASON_SEMANTIC_OPTIONAL",
    "REASON_UNKNOWN_PROBE",
    "REASON_WORKSPACE_HYGIENE",
    "REASON_WORKSPACE_HYGIENE_READY",
    "SETUP_DOCTOR_TITLE",
    "SETUP_STATUS_TITLE",
]
