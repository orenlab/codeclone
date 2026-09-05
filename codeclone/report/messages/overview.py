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
KPI_FINDINGS: Final = "Structural findings"
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
CLUSTER_OVERLOADED_MODULES: Final = "Overloaded Modules"
CLUSTER_OVERLOADED_TOP_CANDIDATES: Final = "Top candidates"
CLUSTER_OVERLOADED_MORE_CANDIDATES: Final = "More candidates"
CLUSTER_ANALYTICS: Final = "Analytics"
CLUSTER_HEALTH_PROFILE: Final = "Health Profile"
# The card inside the cluster answers a different question from the cluster
# title over it ("what are these numbers?"), so the two are not one label
# spelled twice.
CLUSTER_HEALTH_PROFILE_LABEL: Final = "Dimension scores"
CLUSTER_RADAR_CAPTION: Final = "Higher values indicate better code health."
CLUSTER_RADAR_CAPTION_SUFFIX: Final = " Red labels highlight dimensions below 60."

EXECUTIVE_SCAN_SCOPE_DEFAULT: Final = (
    "Project-wide context derived from the full scanned root."
)

# --- The executive banner -------------------------------------------------
# The face of the report asks what a reader opens a change controller's
# report to ask: what is new against the accepted baseline. Health is drawn
# by the ring beside the banner and every count by the cards under it; the
# banner used to restate both, so the first screen said each number twice
# and never said the one thing nothing else on it said.
EXECUTIVE_QUESTION: Final = "What changed since the baseline?"
#: The verdict wordings mirror the CLI's run outcome (``ui_messages.runtime``)
#: so a reader meets one vocabulary on both surfaces. The report package does
#: not import that module, so the words are spelled here for this page.
BASELINE_NOTHING_NEW: Final = "Nothing new since the baseline."
BASELINE_NEW_PREFIX: Final = "New since the baseline: "
BASELINE_NOT_COMPARED: Final = "Not compared: {reason}."
BASELINE_REASON_MISSING: Final = "no baseline yet"
BASELINE_REASON_STATE: Final = "baseline {state}"
BASELINE_FIRST_RUN_WHY: Final = (
    "CodeClone reports what changed in your code's structure against an "
    "accepted baseline; today's findings become known debt once you create one."
)
#: A clone group whose baseline lane was unavailable has no novelty verdict;
#: the banner says how many, in words, instead of counting them as "nothing
#: new". Said without the word "lane": three blind readers of the first
#: draft read "baseline lane unavailable" under a "Baseline verified" pill as
#: a contradiction they could not resolve.
BASELINE_LANES_NOT_COMPARED: Final = (
    "{count} clone {noun} could not be compared: no baseline verdict."
)
#: The commands that apply to each verdict, as the CLI offers them.
BASELINE_ACTION_CREATE: Final = (
    "Create the baseline:",
    "codeclone . --update-baseline",
)
BASELINE_ACTION_BLOCK: Final = ("Block it in CI:", "codeclone . --fail-on-new")
BASELINE_ACTION_ACCEPT: Final = (
    "Accept as known debt:",
    "codeclone . --update-baseline",
)
#: The families the banner names when they carry something new, in the order
#: the KPI cards draw them, with the noun each count takes.
BASELINE_NEW_FAMILIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("clones", "clone group", "clone groups"),
    ("complexity", "high-complexity function", "high-complexity functions"),
    ("coupling", "high-coupling class", "high-coupling classes"),
    ("dead_code", "dead-code item", "dead-code items"),
    ("dep_cycles", "dependency cycle", "dependency cycles"),
)
#: The clones-only run has no metric families to compare; the banner says so
#: in the same breath as its verdict, in its own lower-case spelling. The
#: five family panels state the shared ``METRICS_SKIPPED`` sentence, and a
#: sixth site of that exact string would read as a sixth skipped family.
EXECUTIVE_METRICS_SKIPPED: Final = "Metrics were skipped for this run."
#: What a KPI card says under its number once the comparison found nothing
#: new in that family. "baselined" named the mechanism; this names the fact.
KPI_NOTHING_NEW: Final = "nothing new"
#: The card's delta badge: the count and the word, so "+1" on a clone card is
#: not read as the same kind of thing as "+3" on the health ring.
KPI_NEW_BADGE: Final = "+{count} new"
KPI_NOT_COMPARED: Final = "not compared"
HEALTH_DELTA_SUFFIX: Final = " since baseline"

ADOPTION_API_DISABLED: Final = "Disabled in this run."
# The API card's absence sentence: the surface was measured, but the baseline
# comparison never ran, so there are no breaking/added facts to show. Said in
# words because omitting the rows rendered a withheld run identical to
# "compared, nothing to report".
ADOPTION_API_DIFF_UNAVAILABLE: Final = (
    "Baseline comparison is unavailable for this run."
)

ADOPTION_CLUSTER_TITLE: Final = "Adoption & API"
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
#
# Each tier is one fact row: what it is, whether it ran, and -- when it did
# not -- the flag that turns it on. That is what a reader of an empty state
# asks; the two cards of three rows and two sentences this replaced answered
# nothing a row does not.
TIER_CLUSTER_TITLE: Final = "Advisory detection tiers"
TIER_CLUSTER_DESC: Final = (
    "Reported beside the clone lane: no baseline verdict, no gate, not "
    "counted in the findings above."
)
TIER_CLUSTER_ITEM_LABEL: Final = "Opt-in detectors"
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
#: The flag that turns each tier on: the one thing a reader of a tier that
#: did not run needs beside the fact that it did not run.
TIER_ENABLE_FLAGS: Final[dict[str, str]] = {
    "near_miss": "--near-miss",
    "renamed_structure": "--renamed-structure",
}
TIER_STATE_LABEL_DISABLED: Final = "not run"
TIER_STATE_LABEL_COMPLETE: Final = "measured"
TIER_ENABLE_WITH: Final = "enable with"
TIER_REVISION: Final = "algorithm r{revision}"
