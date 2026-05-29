# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Structural finding explainability copy."""

from __future__ import annotations

from typing import Final

from ...domain.findings import (
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
)

STRUCTURAL_KIND_LABELS: Final[dict[str, str]] = {
    STRUCTURAL_KIND_DUPLICATED_BRANCHES: "Duplicated branches",
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: "Clone guard/exit divergence",
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT: "Clone cohort drift",
}

STRUCTURAL_INTRO_QUESTION: Final = "What are structural findings?"
STRUCTURAL_INTRO_ANSWER: Final = (
    "Repeated non-overlapping branch-body shapes detected inside individual "
    "functions. These are local, report-only refactoring hints and do not "
    "affect clone detection or CI verdicts."
)
STRUCTURAL_EMPTY: Final = "No structural findings detected."
STRUCTURAL_WHY_BUTTON: Final = "Why?"
STRUCTURAL_INLINE_ACTION_LABEL: Final = "Suggested action"
STRUCTURAL_SECTION_IMPACT: Final = "Impact"
STRUCTURAL_SECTION_DETECTION_RATIONALE: Final = "Detection Rationale"
STRUCTURAL_SECTION_SIGNATURE: Final = "Signature"
STRUCTURAL_SECTION_EXAMPLES: Final = "Examples"
TAB_LABEL_ALL: Final = "All"

REPORT_ONLY_NO_GATING: Final = (
    "This is a report-only finding and does not affect clone gating."
)
REPORT_ONLY_LOCAL_HINT: Final = (
    "This is a local, report-only hint. It does not change clone groups or CI verdicts."
)

GUARD_DIVERGENCE_MEMBERS: Final = (
    "{count} divergent clone members were detected after "
    "stable sorting and deduplication."
)
GUARD_DIVERGENCE_COMPARE: Final = (
    "Members were compared by entry-guard count/profile, terminal "
    "kind, and side-effect-before-guard marker."
)
GUARD_DIVERGENCE_COHORT: Final = (
    "Cohort id: {cohort_id}; majority guard count: {majority_guard_count}."
)
DRIFT_MEMBERS: Final = "{count} clone members diverge from the cohort majority profile."
DRIFT_FIELDS: Final = "Drift fields: {drift_fields}."
DRIFT_COHORT: Final = "Cohort id: {cohort_id} with arity {cohort_arity}."
DRIFT_MAJORITY: Final = (
    "Majority profile is compared deterministically with lexical tie-breaks."
)

BRANCH_BODIES_REMAINED: Final = (
    "{count} non-overlapping branch bodies remained after "
    "deduplication and overlap pruning."
)
SIGNATURE_GROUPED: Final = (
    "The detector grouped them by structural signature: "
    "stmt seq: {stmt_seq}, terminal: {terminal}."
)
SIGNATURE_MATCH_RULE: Final = (
    "Call/raise buckets and nested control-flow flags must also match "
    "for branches to land in the same finding group."
)

SPREAD_INCLUDES: Final = (
    "Spread includes {functions} {func_word} in {files} {file_word}."
)
SPREAD_ALL_OCCURRENCES: Final = (
    "All occurrences belong to {functions} {func_word} in {files} {file_word}."
)

IMPACT_GUARD_DIVERGENCE: Final = (
    "Members of one function-clone cohort diverged in guard/exit behavior. "
    "This often points to a partial fix where one path was updated and "
    "other siblings were left unchanged."
)
IMPACT_COHORT_DRIFT: Final = (
    "Members of one function-clone cohort drifted from a stable majority "
    "profile (terminal, guard, try/finally, side-effect order). Review "
    "whether divergence is intentional."
)
IMPACT_CROSS_FUNCTION: Final = (
    "This pattern repeats across {functions} functions and "
    "{files} files, so the same branch policy may be copied "
    "between multiple code paths."
)
IMPACT_TERMINAL_RAISE: Final = (
    "This group points to repeated guard or validation exits inside one "
    "function. Consolidating the shared exit policy usually reduces "
    "branch noise."
)
IMPACT_TERMINAL_RETURN: Final = (
    "This group points to repeated return-path logic inside one function. "
    "A helper can often keep the branch predicate local while sharing "
    "the emitted behavior."
)
IMPACT_DEFAULT_BRANCHES: Final = (
    "This group reports {count} branches with the same local shape "
    "({signature}). Review whether the local branch logic should stay "
    "duplicated or be simplified in place."
)

DETECTION_RATIONALE_INTRO: Final = (
    "CodeClone reported this group because it found {count} {subject} {scope}."
)

SHOWING_BRANCHES: Final = (
    "Showing the first {shown} matching branches from {total} total occurrences."
)
SHOWING_GUARD_DIVERGENCE: Final = (
    "Showing the first {shown} cohort members from {total} divergent occurrences."
)
SHOWING_COHORT_DRIFT: Final = (
    "Showing the first {shown} cohort members from {total} divergent occurrences."
)

SUBJECT_BRANCH_BODIES: Final = "structurally matching branch bodies"
SUBJECT_GUARD_DIVERGENCE: Final = "clone cohort members with guard/exit divergence"
SUBJECT_COHORT_DRIFT: Final = "clone cohort members that drift from majority profile"

EXAMPLE_LABEL_AB: Final = ("A", "B")


def plural_word(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def fmt_spread(functions: int, files: int, *, template: str = SPREAD_INCLUDES) -> str:
    return template.format(
        functions=functions,
        func_word=plural_word(functions, "function", "functions"),
        files=files,
        file_word=plural_word(files, "file", "files"),
    )
