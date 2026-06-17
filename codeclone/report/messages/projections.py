# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Text and Markdown report projection headings."""

from __future__ import annotations

from typing import Final

PROJECTION_NONE: Final = "(none)"
MD_TITLE: Final = "# CodeClone Report"

TEXT_SECTION_REPORT_METADATA: Final = "REPORT METADATA"
TEXT_SECTION_INVENTORY: Final = "INVENTORY"
TEXT_SECTION_FINDINGS_SUMMARY: Final = "FINDINGS SUMMARY"
TEXT_SECTION_METRICS_SUMMARY: Final = "METRICS SUMMARY"
TEXT_SECTION_DERIVED_OVERVIEW: Final = "DERIVED OVERVIEW"
TEXT_SECTION_INTEGRITY: Final = "INTEGRITY"
TEXT_SECTION_SUGGESTIONS: Final = "SUGGESTIONS"
TEXT_SECTION_FUNCTION_CLONES: Final = "FUNCTION CLONES"
TEXT_SECTION_BLOCK_CLONES: Final = "BLOCK CLONES"
TEXT_SECTION_SEGMENT_CLONES: Final = "SEGMENT CLONES"
TEXT_SECTION_SUPPRESSED_FUNCTION_CLONES: Final = "SUPPRESSED FUNCTION CLONES"
TEXT_SECTION_SUPPRESSED_BLOCK_CLONES: Final = "SUPPRESSED BLOCK CLONES"
TEXT_SECTION_SUPPRESSED_SEGMENT_CLONES: Final = "SUPPRESSED SEGMENT CLONES"
TEXT_SECTION_STRUCTURAL_FINDINGS: Final = "STRUCTURAL FINDINGS"
TEXT_SECTION_DEAD_CODE_FINDINGS: Final = "DEAD CODE FINDINGS"
TEXT_SECTION_DESIGN_FINDINGS: Final = "DESIGN FINDINGS"
TEXT_SECTION_SUPPRESSED_DEAD_CODE: Final = "SUPPRESSED DEAD CODE"
TEXT_SECTION_COVERAGE_JOIN: Final = "COVERAGE JOIN (top 10)"
TEXT_SECTION_OVERLOADED_MODULES: Final = "OVERLOADED MODULES (top 10)"
TEXT_SECTION_SECURITY_SURFACES: Final = "SECURITY SURFACES (top 10)"
TEXT_BASELINE_UNTRUSTED_NOTE: Final = (
    "Note: baseline is untrusted; all groups are treated as NEW."
)

TEXT_OVERVIEW_FAMILIES: Final = "Families:"
TEXT_OVERVIEW_SOURCE_SCOPE: Final = "Source scope breakdown:"
TEXT_OVERVIEW_HEALTH_SNAPSHOT: Final = "Health snapshot:"
TEXT_OVERVIEW_HOTLISTS: Final = "Hotlists:"
TEXT_OVERVIEW_TOP_RISKS: Final = "Top risks:"
TEXT_OVERVIEW_TOP_RISKS_NONE: Final = "Top risks: (none)"

TEXT_META_REPORT_SCHEMA_VERSION: Final = "Report schema version: "
TEXT_META_CODECLONE_VERSION: Final = "CodeClone version: "
TEXT_META_PROJECT_NAME: Final = "Project name: "
TEXT_META_SCAN_ROOT: Final = "Scan root: "
TEXT_META_PYTHON_VERSION: Final = "Python version: "
TEXT_META_PYTHON_TAG: Final = "Python tag: "
TEXT_META_ANALYSIS_MODE: Final = "Analysis mode: "
TEXT_META_REPORT_MODE: Final = "Report mode: "
TEXT_META_REPORT_GENERATED: Final = "Report generated (UTC): "
TEXT_META_COMPUTED_METRIC_FAMILIES: Final = "Computed metric families: "
TEXT_META_BASELINE_PATH: Final = "Baseline path: "
TEXT_META_BASELINE_FINGERPRINT_VERSION: Final = "Baseline fingerprint version: "
TEXT_META_BASELINE_SCHEMA_VERSION: Final = "Baseline schema version: "
TEXT_META_BASELINE_PYTHON_TAG: Final = "Baseline Python tag: "
TEXT_META_BASELINE_GENERATOR_NAME: Final = "Baseline generator name: "
TEXT_META_BASELINE_GENERATOR_VERSION: Final = "Baseline generator version: "
TEXT_META_BASELINE_PAYLOAD_SHA256: Final = "Baseline payload sha256: "
TEXT_META_BASELINE_PAYLOAD_VERIFIED: Final = "Baseline payload verified: "
TEXT_META_BASELINE_LOADED: Final = "Baseline loaded: "
TEXT_META_BASELINE_STATUS: Final = "Baseline status: "
TEXT_META_CACHE_PATH: Final = "Cache path: "
TEXT_META_CACHE_SCHEMA_VERSION: Final = "Cache schema version: "
TEXT_META_CACHE_STATUS: Final = "Cache status: "
TEXT_META_CACHE_USED: Final = "Cache used: "
TEXT_META_METRICS_BASELINE_PATH: Final = "Metrics baseline path: "
TEXT_META_METRICS_BASELINE_LOADED: Final = "Metrics baseline loaded: "
TEXT_META_METRICS_BASELINE_STATUS: Final = "Metrics baseline status: "
TEXT_META_METRICS_BASELINE_SCHEMA_VERSION: Final = "Metrics baseline schema version: "
TEXT_META_METRICS_BASELINE_PAYLOAD_SHA256: Final = "Metrics baseline payload sha256: "
TEXT_META_METRICS_BASELINE_PAYLOAD_VERIFIED: Final = (
    "Metrics baseline payload verified: "
)

TEXT_INVENTORY_FILES: Final = "Files: "
TEXT_INVENTORY_CODE: Final = "Code: "
TEXT_INVENTORY_FILE_REGISTRY: Final = "File registry: "

TEXT_FINDINGS_TOTAL_GROUPS: Final = "Total groups: "
TEXT_FINDINGS_FAMILIES: Final = "Families: "
TEXT_FINDINGS_SEVERITY: Final = "Severity: "
TEXT_FINDINGS_IMPACT_SCOPE: Final = "Impact scope: "
TEXT_FINDINGS_CLONES: Final = "Clones: "
TEXT_FINDINGS_SUPPRESSED: Final = "Suppressed: "

TEXT_INTEGRITY_CANONICALIZATION: Final = "Canonicalization: "
TEXT_INTEGRITY_DIGEST: Final = "Digest: "

TEXT_STRUCTURAL_FINDINGS_HEADER: Final = "STRUCTURAL FINDINGS (groups={count})"
TEXT_SUPPRESSED_DEAD_CODE_HEADER: Final = "SUPPRESSED DEAD CODE (items={count})"
TEXT_SUGGESTIONS_HEADER: Final = "SUGGESTIONS (count={count})"
