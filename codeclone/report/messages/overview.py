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
# Distinct from KPI_HEALTH_NA on purpose: "n/a" is what a clones-only run
# shows because health was never computed. This is what a full run shows when
# health was computed over a population of nothing — the card must not draw a
# ring, a score or a grade for code the run never opened.
KPI_HEALTH_UNMEASURED: Final = "not measured"
KPI_HEALTH_UNMEASURED_TIP: Final = (
    "No source file was read, so no health score was measured for this run"
)
# Worded apart from the card above so each can be pinned on its own: a test
# that matched one string could not tell which of the two actually fired.
EXECUTIVE_HEALTH_UNMEASURED: Final = (
    "This run read no source file, so it measured no health."
)
# The third "no number" card, and the third distinct fact. "n/a" is health
# never computed; "not measured" is a population that existed and went unread;
# this one is a scope that holds no source file. The run worked — there is
# simply nothing here to score, and a ring at 90 would say the opposite.
KPI_HEALTH_EMPTY_SCOPE: Final = "no source in scope"
KPI_HEALTH_EMPTY_SCOPE_TIP: Final = (
    "The analysis scope contains no source file, so there is no health to score"
)
EXECUTIVE_HEALTH_EMPTY_SCOPE: Final = (
    "This run found no source file in scope, so there is no health to measure."
)
#: Population states that draw no ring, each with its card text, tip and
#: executive sentence. One table so the card, the tip and the sentence cannot
#: drift apart, and so a state added without a row here fails visibly instead
#: of rendering a gauge over nothing.
HEALTH_ABSENCE_CARDS: Final[dict[str, tuple[str, str, str]]] = {
    "unmeasured": (
        KPI_HEALTH_UNMEASURED,
        KPI_HEALTH_UNMEASURED_TIP,
        EXECUTIVE_HEALTH_UNMEASURED,
    ),
    "complete_empty": (
        KPI_HEALTH_EMPTY_SCOPE,
        KPI_HEALTH_EMPTY_SCOPE_TIP,
        EXECUTIVE_HEALTH_EMPTY_SCOPE,
    ),
}
ISSUE_BREAKDOWN_EMPTY: Final = "No issues detected"
# An empty result and an unmeasured one look identical unless the panel
# says which one it is.
ISSUE_BREAKDOWN_EMPTY_REASON: Final = (
    "Clone, structural, dead-code and design families were all analysed and "
    "each returned nothing."
)

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
# The face of the report asks what a reader opens it to ask, in the same
# slot every other panel uses for its question.
EXECUTIVE_HEALTH_SNAPSHOT_QUESTION: Final = "How healthy is this repository right now?"
EXECUTIVE_THRESHOLDS_PREFIX: Final = "Thresholds: "

ADOPTION_API_DISABLED: Final = "Disabled in this run."
# The API card's absence sentence: the surface was measured, but the baseline
# comparison never ran, so there are no breaking/added facts to show. Said in
# words because omitting the rows rendered a withheld run identical to
# "compared, nothing to report".
ADOPTION_API_DIFF_UNAVAILABLE: Final = (
    "Baseline comparison is unavailable for this run."
)

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

# --- Advisory detection tiers -------------------------------------------
# The two tiers beside the clone lane. Before this cluster existed the HTML
# report named them nowhere at all: a reader could not tell whether a tier had
# run and found nothing or had never run, because the page showed neither.
#
# Every string below is a label. The page restates the container's own `state`
# and `count` and derives nothing: a tier that reports no count is drawn with
# no count, never with a zero, because a zero here is a measurement and the
# renderer has none to make.
TIER_CLUSTER_TITLE: Final = "Advisory detection tiers"
TIER_CLUSTER_DESC: Final = (
    "Reported beside the clone lane, never inside it: these records reach no "
    "baseline lane, carry no novelty verdict, and trip no gate. They are not "
    "counted in the findings total above."
)
# The tier containers this page draws, in the order it draws them. The
# presentation ring cannot import the domain vocabulary that names them
# (`codeclone.domain.findings` is r2, this module and the HTML sections are
# r4, and the boundary ratchet holds that line), so the surface declares its
# own display list and the agreement is held by the document instead: the page
# draws exactly the containers `findings.groups` carries that appear here, and
# `test_tier_surface_declaration` pins that every tier container a canonical
# document holds is one this list covers.
TIER_DISPLAY_ORDER: Final[tuple[str, ...]] = ("near_miss", "renamed_structure")
TIER_LABELS: Final[dict[str, str]] = {
    "near_miss": "Near-miss pairs",
    "renamed_structure": "Renamed structure groups",
}
TIER_ROW_STATE: Final = "State"
TIER_ROW_COUNT: Final = "Measured"
TIER_ROW_REVISION: Final = "Algorithm revision"
TIER_STATE_LABEL_DISABLED: Final = "disabled — never ran"
TIER_STATE_LABEL_COMPLETE: Final = "complete — measured"
# A tier that never ran has no measurement to draw, and a "0" beside it would
# read as one. The absence is stated in words instead.
TIER_COUNT_ABSENT: Final = "no measurement in this run"
TIER_DISABLED_HINT: Final = (
    "The producer was never invoked, so this tier has no count. The revision "
    "shown is the algorithm the opt-in would run, not evidence that it ran."
)
TIER_COMPLETE_HINT: Final = (
    "The producer ran to completion, so this count is a finished measurement. "
    "A count of 0 here means it measured nothing, never that it did not "
    "measure."
)
