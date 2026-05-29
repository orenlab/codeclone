# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""FastMCP server instructions and install hints."""

from __future__ import annotations

from typing import Final

SERVER_INSTRUCTIONS: Final = (
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

MCP_INSTALL_HINT: Final = (
    "CodeClone MCP support requires the optional 'mcp' extra. "
    "Install it with: pip install 'codeclone[mcp]'"
)
