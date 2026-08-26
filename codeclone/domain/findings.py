# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

SYMBOL_KIND_FUNCTION: Final = "function"
SYMBOL_KIND_CLASS: Final = "class"
SYMBOL_KIND_METHOD: Final = "method"
SYMBOL_KIND_IMPORT: Final = "import"

CLONE_NOVELTY_NEW: Final = "new"
CLONE_NOVELTY_KNOWN: Final = "known"
CLONE_NOVELTY_UNAVAILABLE: Final = "unavailable"

FAMILY_CLONE: Final = "clone"
FAMILY_STRUCTURAL: Final = "structural"
FAMILY_DEAD_CODE: Final = "dead_code"
FAMILY_DESIGN: Final = "design"
FAMILY_AUTHORITY: Final = "authority"
FAMILY_METRICS: Final = "metrics"

#: The finding families a baseline tracks. ``findings.summary.total`` and every
#: consumer total are computed over exactly these: each one owns baseline-lane
#: keys, so its members can carry a ``new`` / ``known`` novelty verdict.
BASELINE_TRACKED_FAMILIES: Final[tuple[str, ...]] = (
    FAMILY_CLONE,
    FAMILY_STRUCTURAL,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_AUTHORITY,
)

#: The advisory detection tiers. They are siblings of the clone lane, never
#: members of it: their records reach no baseline lane, so ``gate_relevant`` is
#: false and ``novelty`` is ``untracked`` — neither ``new`` nor ``known`` is a
#: claim any baseline could support.
#:
#: These names are *not* finding families and never widen a published total.
#: They key the two containers at ``findings.groups.<tier>`` and are the
#: vocabulary every consumer surface uses to name the tier it is showing —
#: MCP's explicit ``family`` values, the HTML tier rows, and the subset
#: declarations the markdown/text/SARIF projections carry. One owner, because
#: a name spelled independently in four surfaces is four chances to disagree.
TIER_NEAR_MISS: Final = "near_miss"
TIER_RENAMED_STRUCTURE: Final = "renamed_structure"
ADVISORY_TIER_NAMES: Final[tuple[str, ...]] = (
    TIER_NEAR_MISS,
    TIER_RENAMED_STRUCTURE,
)

#: Where each tier container lists its records. The two tiers differ by
#: construction — edit distance is not transitive, so near-miss evidence is
#: pairwise, while digest equality is, so renamed structure is a group — and
#: the key names that difference rather than flattening it.
ADVISORY_TIER_RECORD_KEYS: Final[dict[str, str]] = {
    TIER_NEAR_MISS: "pairs",
    TIER_RENAMED_STRUCTURE: "groups",
}

CATEGORY_CLONE: Final = "clone"
CATEGORY_STRUCTURAL: Final = "structural"
CATEGORY_COMPLEXITY: Final = "complexity"
CATEGORY_COUPLING: Final = "coupling"
CATEGORY_COHESION: Final = "cohesion"
CATEGORY_DEAD_CODE: Final = "dead_code"
CATEGORY_DEPENDENCY: Final = "dependency"
CATEGORY_COVERAGE: Final = "coverage"
CATEGORY_DESIGN: Final = "design"

FINDING_KIND_CLONE_GROUP: Final = "clone_group"
FINDING_KIND_UNUSED_SYMBOL: Final = "unused_symbol"
# The dead_code family's second kind. Unlike a dead symbol - which subdivides
# into function/class/method - an unreachable statement has no sub-kind, so
# this one name serves as both the finding kind and the dispatch category.
FINDING_KIND_UNREACHABLE_STATEMENT: Final = "unreachable_statement"
FINDING_KIND_CLASS_HOTSPOT: Final = "class_hotspot"
FINDING_KIND_FUNCTION_HOTSPOT: Final = "function_hotspot"
FINDING_KIND_CYCLE: Final = "cycle"
FINDING_KIND_UNTESTED_HOTSPOT: Final = "untested_hotspot"
FINDING_KIND_COVERAGE_HOTSPOT: Final = "coverage_hotspot"
FINDING_KIND_COVERAGE_SCOPE_GAP: Final = "coverage_scope_gap"
FINDING_KIND_AUTHORITY_VIOLATION: Final = "authority_violation"

DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD: Final = "instance_independent_method"

# Classifications for instance-independent method occurrences.
# Only ``candidate`` is a default-surfaced signal; the rest are context or
# suppressed so default payloads avoid noisy contract methods.
IIM_CLASSIFICATION_CANDIDATE: Final = "candidate"
IIM_CLASSIFICATION_DECORATED_CONTEXT: Final = "decorated_context"
IIM_CLASSIFICATION_INTERFACE_CONTRACT: Final = "interface_contract"
IIM_CLASSIFICATION_OVERRIDE_CONTEXT: Final = "override_context"
IIM_CLASSIFICATION_PROPERTY_LIKE: Final = "property_like"
IIM_CLASSIFICATION_DUNDER_PROTOCOL: Final = "dunder_protocol"
IIM_CLASSIFICATION_NOOP_STUB: Final = "noop_stub"

STRUCTURAL_KIND_DUPLICATED_BRANCHES: Final = "duplicated_branches"
STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: Final = "clone_guard_exit_divergence"
STRUCTURAL_KIND_CLONE_COHORT_DRIFT: Final = "clone_cohort_drift"

__all__ = [
    "CATEGORY_CLONE",
    "CATEGORY_COHESION",
    "CATEGORY_COMPLEXITY",
    "CATEGORY_COUPLING",
    "CATEGORY_COVERAGE",
    "CATEGORY_DEAD_CODE",
    "CATEGORY_DEPENDENCY",
    "CATEGORY_DESIGN",
    "CATEGORY_STRUCTURAL",
    "CLONE_NOVELTY_KNOWN",
    "CLONE_NOVELTY_NEW",
    "CLONE_NOVELTY_UNAVAILABLE",
    "DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD",
    "FAMILY_AUTHORITY",
    "FAMILY_CLONE",
    "FAMILY_DEAD_CODE",
    "FAMILY_DESIGN",
    "FAMILY_METRICS",
    "FAMILY_STRUCTURAL",
    "FINDING_KIND_AUTHORITY_VIOLATION",
    "FINDING_KIND_CLASS_HOTSPOT",
    "FINDING_KIND_CLONE_GROUP",
    "FINDING_KIND_COVERAGE_HOTSPOT",
    "FINDING_KIND_COVERAGE_SCOPE_GAP",
    "FINDING_KIND_CYCLE",
    "FINDING_KIND_FUNCTION_HOTSPOT",
    "FINDING_KIND_UNREACHABLE_STATEMENT",
    "FINDING_KIND_UNTESTED_HOTSPOT",
    "FINDING_KIND_UNUSED_SYMBOL",
    "IIM_CLASSIFICATION_CANDIDATE",
    "IIM_CLASSIFICATION_DECORATED_CONTEXT",
    "IIM_CLASSIFICATION_DUNDER_PROTOCOL",
    "IIM_CLASSIFICATION_INTERFACE_CONTRACT",
    "IIM_CLASSIFICATION_NOOP_STUB",
    "IIM_CLASSIFICATION_OVERRIDE_CONTEXT",
    "IIM_CLASSIFICATION_PROPERTY_LIKE",
    "STRUCTURAL_KIND_CLONE_COHORT_DRIFT",
    "STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE",
    "STRUCTURAL_KIND_DUPLICATED_BRANCHES",
    "SYMBOL_KIND_CLASS",
    "SYMBOL_KIND_FUNCTION",
    "SYMBOL_KIND_IMPORT",
    "SYMBOL_KIND_METHOD",
]
