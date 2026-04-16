# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

CLONE_KIND_FUNCTION: Final = "function"
CLONE_KIND_BLOCK: Final = "block"
CLONE_KIND_SEGMENT: Final = "segment"

SYMBOL_KIND_FUNCTION: Final = "function"
SYMBOL_KIND_CLASS: Final = "class"
SYMBOL_KIND_METHOD: Final = "method"
SYMBOL_KIND_IMPORT: Final = "import"

CLONE_NOVELTY_NEW: Final = "new"
CLONE_NOVELTY_KNOWN: Final = "known"

FAMILY_CLONE: Final = "clone"
FAMILY_CLONES: Final = "clones"
FAMILY_STRUCTURAL: Final = "structural"
FAMILY_DEAD_CODE: Final = "dead_code"
FAMILY_DESIGN: Final = "design"
FAMILY_METRICS: Final = "metrics"

CATEGORY_CLONE: Final = "clone"
CATEGORY_STRUCTURAL: Final = "structural"
CATEGORY_COMPLEXITY: Final = "complexity"
CATEGORY_COUPLING: Final = "coupling"
CATEGORY_COHESION: Final = "cohesion"
CATEGORY_DEAD_CODE: Final = "dead_code"
CATEGORY_DEPENDENCY: Final = "dependency"
CATEGORY_COVERAGE: Final = "coverage"

FINDING_KIND_CLONE_GROUP: Final = "clone_group"
FINDING_KIND_UNUSED_SYMBOL: Final = "unused_symbol"
FINDING_KIND_CLASS_HOTSPOT: Final = "class_hotspot"
FINDING_KIND_FUNCTION_HOTSPOT: Final = "function_hotspot"
FINDING_KIND_CYCLE: Final = "cycle"
FINDING_KIND_UNTESTED_HOTSPOT: Final = "untested_hotspot"
FINDING_KIND_COVERAGE_HOTSPOT: Final = "coverage_hotspot"
FINDING_KIND_COVERAGE_SCOPE_GAP: Final = "coverage_scope_gap"

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
    "CATEGORY_STRUCTURAL",
    "CLONE_KIND_BLOCK",
    "CLONE_KIND_FUNCTION",
    "CLONE_KIND_SEGMENT",
    "CLONE_NOVELTY_KNOWN",
    "CLONE_NOVELTY_NEW",
    "FAMILY_CLONE",
    "FAMILY_CLONES",
    "FAMILY_DEAD_CODE",
    "FAMILY_DESIGN",
    "FAMILY_METRICS",
    "FAMILY_STRUCTURAL",
    "FINDING_KIND_CLASS_HOTSPOT",
    "FINDING_KIND_CLONE_GROUP",
    "FINDING_KIND_COVERAGE_HOTSPOT",
    "FINDING_KIND_COVERAGE_SCOPE_GAP",
    "FINDING_KIND_CYCLE",
    "FINDING_KIND_FUNCTION_HOTSPOT",
    "FINDING_KIND_UNTESTED_HOTSPOT",
    "FINDING_KIND_UNUSED_SYMBOL",
    "STRUCTURAL_KIND_CLONE_COHORT_DRIFT",
    "STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE",
    "STRUCTURAL_KIND_DUPLICATED_BRANCHES",
    "SYMBOL_KIND_CLASS",
    "SYMBOL_KIND_FUNCTION",
    "SYMBOL_KIND_IMPORT",
    "SYMBOL_KIND_METHOD",
]
