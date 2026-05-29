# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Suggestion titles, fact kinds, summaries, and action steps."""

from __future__ import annotations

from typing import Final

from ...domain.findings import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
)

CLONE_FACT_KIND_FUNCTION: Final = "Function clone group"
CLONE_FACT_KIND_BLOCK: Final = "Block clone group"
CLONE_FACT_KIND_SEGMENT: Final = "Segment clone group"

CLONE_FACT_KIND_BY_KIND: Final[dict[str, str]] = {
    CLONE_KIND_FUNCTION: CLONE_FACT_KIND_FUNCTION,
    CLONE_KIND_BLOCK: CLONE_FACT_KIND_BLOCK,
    CLONE_KIND_SEGMENT: CLONE_FACT_KIND_SEGMENT,
}

CLONE_SUMMARY_FUNCTION_TYPE1: Final = "same exact function body"
CLONE_SUMMARY_FUNCTION_TYPE2: Final = "same parameterized function body"
CLONE_SUMMARY_FUNCTION_TYPE3: Final = (
    "same structural function body with small identifier changes"
)
CLONE_SUMMARY_FUNCTION_TYPE4: Final = "same structural function body"
CLONE_SUMMARY_BLOCK_ASSERT_ONLY: Final = "same assertion template"
CLONE_SUMMARY_BLOCK_REPEATED_STMT: Final = "same repeated setup/assert pattern"
CLONE_SUMMARY_BLOCK_DEFAULT: Final = "same structural sequence with small value changes"
CLONE_SUMMARY_SEGMENT: Final = "same structural segment sequence"

CLONE_STEP_TYPE1_1: Final = (
    "Keep one canonical implementation and remove the exact duplicates."
)
CLONE_STEP_TYPE1_2: Final = (
    "Route the remaining call sites to the shared implementation."
)
CLONE_STEP_TYPE2_1: Final = "Extract a shared implementation with explicit parameters."
CLONE_STEP_TYPE2_2: Final = "Replace identifier-only variations with arguments."
CLONE_STEP_BLOCK_ASSERT_1: Final = (
    "Collapse the repeated assertion template into a helper or loop."
)
CLONE_STEP_BLOCK_ASSERT_2: Final = (
    "Keep the asserted values as data instead of copy-pasted statements."
)
CLONE_STEP_BLOCK_1: Final = "Extract the repeated statement sequence into a helper."
CLONE_STEP_BLOCK_2: Final = (
    "Keep setup data close to the call site and move shared logic out."
)
CLONE_STEP_SEGMENT_1: Final = (
    "Review whether the repeated segment should become shared utility code."
)
CLONE_STEP_SEGMENT_2: Final = (
    "Keep this as a report hint only if the duplication is intentional."
)
CLONE_STEP_DEFAULT_1: Final = "Extract the repeated logic into a shared abstraction."
CLONE_STEP_DEFAULT_2: Final = (
    "Replace the duplicated bodies with calls to the shared code."
)

SUGGESTION_TITLE_REDUCE_COMPLEXITY: Final = "Reduce function complexity"
SUGGESTION_TITLE_REDUCE_COUPLING: Final = "Reduce class coupling"
SUGGESTION_TITLE_SPLIT_COHESION: Final = "Split low-cohesion class"
SUGGESTION_TITLE_DEAD_CODE: Final = "Remove or explicitly keep unused code"
SUGGESTION_TITLE_BREAK_CYCLE: Final = "Break circular dependency"

COMPLEXITY_STEP_1: Final = "Split the function into smaller deterministic stages."
COMPLEXITY_STEP_2: Final = "Extract helper functions for nested branches."
COUPLING_STEP_1: Final = "Reduce external dependencies of this class."
COUPLING_STEP_2: Final = "Move unrelated responsibilities to collaborator classes."
COHESION_STEP_1: Final = "Split class by responsibility boundaries."
COHESION_STEP_2: Final = "Group methods by shared state and extract subcomponents."
DEAD_CODE_STEP_1: Final = "Remove or deprecate the unused symbol."
DEAD_CODE_STEP_2: Final = (
    "If intentionally reserved, add explicit keep marker and test."
)
DEPENDENCY_STEP_1: Final = "Break the cycle by extracting a shared abstraction."
DEPENDENCY_STEP_2: Final = (
    "Invert one dependency edge through an interface or protocol."
)

FACT_KIND_COMPLEXITY_HOTSPOT: Final = "Function complexity hotspot"
FACT_KIND_COUPLING_HOTSPOT: Final = "Class coupling hotspot"
FACT_KIND_LOW_COHESION: Final = "Low cohesion class"
FACT_KIND_DEAD_CODE: Final = "Dead code item"
FACT_KIND_DEPENDENCY_CYCLE: Final = "Dependency cycle"
FACT_KIND_STRUCTURAL: Final = "Structural finding"

STRUCTURAL_TITLE_GUARD_EXIT_DIVERGENCE: Final = "Clone guard/exit divergence"
STRUCTURAL_SUMMARY_GUARD_EXIT_DIVERGENCE: Final = (
    "clone cohort members differ in entry guards or early-exit behavior"
)
STRUCTURAL_TITLE_COHORT_DRIFT: Final = "Clone cohort drift"
STRUCTURAL_SUMMARY_COHORT_DRIFT: Final = (
    "clone cohort members drift from majority terminal/guard/try profile"
)
STRUCTURAL_TITLE_REPEATED_BRANCH: Final = "Repeated branch family"
STRUCTURAL_SUMMARY_RAISE_BRANCH: Final = "same repeated guard/validation branch"
STRUCTURAL_SUMMARY_RETURN_BRANCH: Final = "same repeated return branch"
STRUCTURAL_SUMMARY_LOOP_BRANCH: Final = "same repeated loop branch"
STRUCTURAL_SUMMARY_BRANCH_DEFAULT: Final = "same repeated branch shape"

STRUCTURAL_STEP_GUARD_EXIT_1: Final = (
    "Compare divergent clone members against the majority guard/exit profile."
)
STRUCTURAL_STEP_GUARD_EXIT_2: Final = (
    "If divergence is accidental, align guard exits across the cohort."
)
STRUCTURAL_STEP_COHORT_DRIFT_1: Final = (
    "Review whether cohort drift is intentional for this clone family."
)
STRUCTURAL_STEP_COHORT_DRIFT_2: Final = (
    "If not intentional, reconcile terminal/guard/try profiles across members."
)
STRUCTURAL_STEP_CONTINUE_1: Final = (
    "Review whether the repeated continue guard can be merged into one predicate."
)
STRUCTURAL_STEP_CONTINUE_2: Final = (
    "If separate continue checks keep the local control flow clearer, "
    "keep this as a report-only hint."
)
STRUCTURAL_STEP_RAISE_1: Final = (
    "Factor the repeated validation/guard path into a shared helper."
)
STRUCTURAL_STEP_RAISE_2: Final = (
    "Keep the branch-specific inputs at the call site and share the exit policy."
)
STRUCTURAL_STEP_RETURN_1: Final = (
    "Consolidate the repeated return-path logic into a shared helper."
)
STRUCTURAL_STEP_RETURN_2: Final = (
    "Keep the branch predicate local and share the emitted behavior."
)
STRUCTURAL_STEP_DEFAULT_1: Final = (
    "Review whether the repeated local branch can be simplified in place."
)
STRUCTURAL_STEP_DEFAULT_2: Final = (
    "If the local duplication keeps control flow clearer, keep "
    "this as a report-only hint."
)
