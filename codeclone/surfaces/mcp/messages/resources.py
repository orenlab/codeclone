# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP resource descriptions for FastMCP registration."""

from __future__ import annotations

from typing import Final

LATEST_SUMMARY: Final = "Canonical JSON summary for the latest run in this MCP session."
LATEST_REPORT: Final = "Canonical JSON report for the latest run in this MCP session."
LATEST_HEALTH: Final = "Health snapshot for the latest run in this MCP session."
LATEST_GATES: Final = "Gate evaluation for the latest run in this MCP session."
LATEST_CHANGED: Final = (
    "Changed-files projection for the latest diff-aware run in this session."
)
LATEST_TRIAGE: Final = "Production triage for the latest run in this MCP session."
REPORT_SCHEMA: Final = (
    "JSON schema-style descriptor for the canonical CodeClone report."
)
RUN_SUMMARY: Final = "Canonical JSON summary for a specific CodeClone MCP run."
RUN_REPORT: Final = "Canonical JSON report for a specific CodeClone MCP run."
RUN_FINDING: Final = "Canonical JSON finding group for a specific CodeClone MCP run."

TITLE_LATEST_SUMMARY: Final = "Latest Run Summary"
TITLE_LATEST_REPORT: Final = "Latest Canonical Report"
TITLE_LATEST_HEALTH: Final = "Latest Health Snapshot"
TITLE_LATEST_GATES: Final = "Latest Gate Evaluation"
TITLE_LATEST_CHANGED: Final = "Latest Changed Findings"
TITLE_LATEST_TRIAGE: Final = "Latest Production Triage"
TITLE_REPORT_SCHEMA: Final = "CodeClone Report Schema"
TITLE_RUN_SUMMARY: Final = "Run Summary"
TITLE_RUN_REPORT: Final = "Run Canonical Report"
TITLE_RUN_FINDING: Final = "Run Finding"
