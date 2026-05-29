# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Overview tab labels and directory hotspot copy."""

from __future__ import annotations

from typing import Final

DIRECTORY_BUCKET_LABELS: Final[dict[str, str]] = {
    "all": "All Findings",
    "clones": "Clone Groups",
    "structural": "Structural Findings",
    "complexity": "High Complexity",
    "cohesion": "Low Cohesion",
    "coupling": "High Coupling",
    "dead_code": "Dead Code",
    "dependency": "Dependency Cycles",
}

DIRECTORY_BUCKET_ORDER: Final[tuple[str, ...]] = (
    "all",
    "clones",
    "structural",
    "complexity",
    "cohesion",
    "coupling",
    "dead_code",
    "dependency",
)

DIRECTORY_KIND_LABELS: Final[dict[str, str]] = {
    "clones": "clones",
    "structural": "structural",
    "complexity": "complexity",
    "cohesion": "cohesion",
    "coupling": "coupling",
    "dead_code": "dead code",
    "coverage": "coverage",
    "dependency": "dependency",
}

RADAR_DIMENSIONS: Final[tuple[str, ...]] = (
    "clones",
    "complexity",
    "coupling",
    "cohesion",
    "dead_code",
    "dependencies",
    "coverage",
)

RADAR_LABELS: Final[dict[str, str]] = {
    "clones": "Clones",
    "complexity": "Complexity",
    "coupling": "Coupling",
    "cohesion": "Cohesion",
    "dead_code": "Dead Code",
    "dependencies": "Deps",
    "coverage": "Coverage",
}

KPI_HEALTH: Final = "Health"
KPI_HEALTH_NA: Final = "n/a"
ISSUE_BREAKDOWN_EMPTY: Final = "No issues detected"

ISSUE_BREAKDOWN_ROW_LABELS: Final[dict[str, str]] = {
    "clones": "Clone Groups",
    "structural": "Structural",
    "complexity": "Complexity",
    "cohesion": "Cohesion",
    "coupling": "Coupling",
    "dead_code": "Dead Code",
    "dep_cycles": "Dep. Cycles",
}

KPI_CLONE_GROUPS: Final = "Clone Groups"
KPI_HIGH_COMPLEXITY: Final = "High Complexity"
KPI_HIGH_COUPLING: Final = "High Coupling"
KPI_LOW_COHESION: Final = "Low Cohesion"
KPI_DEP_CYCLES: Final = "Dep. Cycles"
KPI_DEAD_CODE: Final = "Dead Code"
KPI_FINDINGS: Final = "Findings"
KPI_SUGGESTIONS: Final = "Suggestions"

KPI_TIP_CLONE_GROUPS: Final = "Detected code clone groups by detection level"
KPI_TIP_HIGH_COMPLEXITY: Final = "Functions with cyclomatic complexity above threshold"
KPI_TIP_HIGH_COUPLING: Final = "Classes with high coupling between objects (CBO)"
KPI_TIP_LOW_COHESION: Final = "Classes with low internal cohesion (high LCOM4)"
KPI_TIP_DEP_CYCLES: Final = "Circular dependencies between project modules"
KPI_TIP_DEAD_CODE: Final = "Potentially unused functions, classes, or imports"
KPI_TIP_FINDINGS: Final = "Active structural findings reported in production code"
KPI_TIP_SUGGESTIONS: Final = (
    "Actionable recommendations derived from clones, findings, and metrics"
)

CLUSTER_EXECUTIVE_SUMMARY: Final = "Executive Summary"
CLUSTER_ISSUE_BREAKDOWN: Final = "Issue breakdown"
CLUSTER_SOURCE_BREAKDOWN: Final = "Source breakdown"
CLUSTER_HOTSPOTS_BY_DIRECTORY: Final = "Hotspots by Directory"
CLUSTER_HOTSPOTS_BY_DIRECTORY_DESC: Final = (
    "Directories with the highest concentration of findings by category."
)
CLUSTER_OVERLOADED_MODULES: Final = "Overloaded Modules"
CLUSTER_OVERLOADED_TOP_CANDIDATES: Final = "Top candidates"
CLUSTER_OVERLOADED_MORE_CANDIDATES: Final = "More candidates"
CLUSTER_ANALYTICS: Final = "Analytics"
CLUSTER_HEALTH_PROFILE: Final = "Health Profile"
CLUSTER_HEALTH_PROFILE_DESC: Final = "Dimension scores across all quality axes."
CLUSTER_HEALTH_PROFILE_LABEL: Final = "Health profile"
CLUSTER_RADAR_CAPTION: Final = "Higher values indicate better code health."
CLUSTER_RADAR_CAPTION_SUFFIX: Final = " Red labels highlight dimensions below 60."

EXECUTIVE_SCAN_SCOPE_DEFAULT: Final = (
    "Project-wide context derived from the full scanned root."
)
EXECUTIVE_HEALTH_SNAPSHOT_QUESTION: Final = "Current health snapshot"
EXECUTIVE_THRESHOLDS_PREFIX: Final = "Thresholds: "

ADOPTION_API_DISABLED: Final = "Disabled in this run."

ADOPTION_CLUSTER_TITLE: Final = "Adoption & API"
ADOPTION_CLUSTER_DESC: Final = (
    "Type/docstring adoption and public API surface are shown as facts, "
    "not style pressure."
)
ADOPTION_COVERAGE_LABEL: Final = "Adoption coverage"
ADOPTION_API_SURFACE_LABEL: Final = "Public API surface"
ADOPTION_PARAM_ANNOTATIONS: Final = "Param annotations"
ADOPTION_RETURN_ANNOTATIONS: Final = "Return annotations"
ADOPTION_DOCSTRINGS: Final = "Docstrings"
ADOPTION_TYPED_AS_ANY: Final = "Typed as Any"
ADOPTION_ENABLE_VIA: Final = "Enable via"
ADOPTION_ENABLE_VIA_FLAG: Final = "--api-surface"
ADOPTION_PUBLIC_SYMBOLS: Final = "Public symbols"
ADOPTION_MODULES: Final = "Modules"
ADOPTION_BREAKING_CHANGES: Final = "Breaking changes"
ADOPTION_ADDED_SYMBOLS: Final = "Added symbols"
ADOPTION_STRICT_MODE: Final = "Strict mode"
ADOPTION_STRICT_MODE_ENABLED: Final = "enabled"
