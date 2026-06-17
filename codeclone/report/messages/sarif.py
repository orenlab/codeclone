# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""SARIF rule descriptions and remediation copy."""

from __future__ import annotations

from typing import Final

SARIF_HELP_DOCS_SUFFIX: Final = "See [CodeClone docs]({docs_url})."

REMEDIATION_CLONE: Final = (
    "Review the representative occurrence and related occurrences, "
    "then extract shared behavior or keep accepted debt in the baseline."
)
REMEDIATION_DUPLICATED_BRANCHES: Final = (
    "Collapse repeated branch shapes into a shared helper, validator, "
    "or control-flow abstraction where the behavior is intentionally shared."
)
REMEDIATION_GUARD_DIVERGENCE: Final = (
    "Review the clone cohort and reconcile guard or early-exit behavior "
    "if those members are expected to stay aligned."
)
REMEDIATION_COHORT_DRIFT: Final = (
    "Review the clone cohort and reconcile terminal, guard, or try/finally "
    "profiles if the drift is not intentional."
)
REMEDIATION_DEAD_CODE: Final = (
    "Remove the unused symbol or keep it explicitly documented/suppressed "
    "when runtime dynamics call it intentionally."
)
REMEDIATION_LOW_COHESION: Final = (
    "Split the class or regroup behavior so responsibilities become cohesive."
)
REMEDIATION_COMPLEXITY: Final = (
    "Split the function or simplify control flow to reduce complexity."
)
REMEDIATION_COUPLING: Final = (
    "Reduce dependencies or split responsibilities to lower coupling."
)
REMEDIATION_DEPENDENCY_CYCLE: Final = (
    "Break the cycle or invert dependencies so modules no longer depend "
    "on each other circularly."
)

RULE_FUNCTION_CLONE_SHORT: Final = "Function clone group"
RULE_FUNCTION_CLONE_FULL: Final = (
    "Multiple functions share the same normalized function body."
)
RULE_BLOCK_CLONE_SHORT: Final = "Block clone group"
RULE_BLOCK_CLONE_FULL: Final = (
    "Repeated normalized statement blocks were detected across occurrences."
)
RULE_SEGMENT_CLONE_SHORT: Final = "Segment clone group"
RULE_SEGMENT_CLONE_FULL: Final = (
    "Repeated normalized statement segments were detected across occurrences."
)

RULE_DUPLICATED_BRANCHES_SHORT: Final = "Duplicated branches"
RULE_DUPLICATED_BRANCHES_FULL: Final = (
    "Repeated branch families with matching structural signatures were detected."
)
RULE_GUARD_DIVERGENCE_SHORT: Final = "Clone guard/exit divergence"
RULE_GUARD_DIVERGENCE_FULL: Final = (
    "Members of the same function-clone cohort diverged in "
    "entry guards or early-exit behavior."
)
RULE_COHORT_DRIFT_SHORT: Final = "Clone cohort drift"
RULE_COHORT_DRIFT_FULL: Final = (
    "Members of the same function-clone cohort drifted from "
    "the majority terminal/guard/try profile."
)

RULE_UNUSED_FUNCTION_SHORT: Final = "Unused function"
RULE_UNUSED_FUNCTION_FULL: Final = "Function appears to be unused with high confidence."
RULE_UNUSED_CLASS_SHORT: Final = "Unused class"
RULE_UNUSED_CLASS_FULL: Final = "Class appears to be unused with high confidence."
RULE_UNUSED_METHOD_SHORT: Final = "Unused method"
RULE_UNUSED_METHOD_FULL: Final = "Method appears to be unused with high confidence."
RULE_UNUSED_SYMBOL_SHORT: Final = "Unused symbol"
RULE_UNUSED_SYMBOL_FULL: Final = "Symbol appears to be unused with reported confidence."

RULE_LOW_COHESION_SHORT: Final = "Low cohesion class"
RULE_LOW_COHESION_FULL: Final = (
    "Class cohesion is low according to LCOM4 hotspot thresholds."
)
RULE_COMPLEXITY_SHORT: Final = "Complexity hotspot"
RULE_COMPLEXITY_FULL: Final = (
    "Function exceeds the project complexity hotspot threshold."
)
RULE_COUPLING_SHORT: Final = "Coupling hotspot"
RULE_COUPLING_FULL: Final = "Class exceeds the project coupling hotspot threshold."
RULE_COVERAGE_SCOPE_GAP_SHORT: Final = "Coverage scope gap"
RULE_COVERAGE_SCOPE_GAP_FULL: Final = (
    "A medium/high-risk function is outside the supplied joined coverage scope."
)
RULE_COVERAGE_HOTSPOT_SHORT: Final = "Coverage hotspot"
RULE_COVERAGE_HOTSPOT_FULL: Final = (
    "A medium/high-risk function falls below the configured joined coverage threshold."
)
RULE_DEPENDENCY_CYCLE_SHORT: Final = "Dependency cycle"
RULE_DEPENDENCY_CYCLE_FULL: Final = (
    "A dependency cycle was detected between project modules."
)

REMEDIATION_BY_RULE_ID: Final[dict[str, str]] = {
    "CCLONE001": REMEDIATION_CLONE,
    "CCLONE002": REMEDIATION_CLONE,
    "CCLONE003": REMEDIATION_CLONE,
    "CSTRUCT001": REMEDIATION_DUPLICATED_BRANCHES,
    "CSTRUCT002": REMEDIATION_GUARD_DIVERGENCE,
    "CSTRUCT003": REMEDIATION_COHORT_DRIFT,
    "CDEAD001": REMEDIATION_DEAD_CODE,
    "CDEAD002": REMEDIATION_DEAD_CODE,
    "CDEAD003": REMEDIATION_DEAD_CODE,
    "CDEAD004": REMEDIATION_DEAD_CODE,
    "CDESIGN001": REMEDIATION_LOW_COHESION,
    "CDESIGN002": REMEDIATION_COMPLEXITY,
    "CDESIGN003": REMEDIATION_COUPLING,
    "CDESIGN004": REMEDIATION_DEPENDENCY_CYCLE,
}
