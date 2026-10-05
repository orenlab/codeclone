# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The normalized state of one run's comparison deltas — one carrier.

The maintainer's ruling (2026-10-03, extended 2026-10-05)::

    comparison performed     -> integer, including 0
    comparison not performed -> null

A ``0`` is a measured comparison result equal to zero; where no comparison
happened, ``0`` is a false statement.  Before this carrier the question
"did this comparison run" was answered in several places: the producer of
the report document (per family, beside the value it zeroed), the producer
of the comparison context (adoption and API, without asking whether the run
collected the surface it compares), the store reader of the availability
rows, a memory reader of the finished document, and every gate input, which
ate the raw metrics diff.  Each answer could be — and was measured to be —
different.

Here the answer has ONE shape: every delta is named by a key that belongs
to no output format, ``(comparison, term)``, and is either
``compared(value)`` or ``not_compared(reason)``.  The producer builds the
state once from the run's comparison facts (``core.comparison_state``); the
report document, the run store, the MCP answers, the CLI and the gates read
it, and each surface differs only in how it SPELLS a key and how it presents
a ``not_compared`` — never in deciding whether the comparison ran.

The reason vocabulary is the comparison house's own availability words, so
a reason read back from the store's rows is the reason the producer wrote:
``disabled`` (the run did not enable the capability), ``unavailable`` (a lane
the comparison reads is not trusted — no baseline, an untrusted container,
a lane under an older schema), ``not_compared`` (the lanes are trusted and
the comparison still did not run: the current half was not observed, the
health verdict was withheld, the baseline carries no term for it).

This module is the vocabulary and the rule, in the contract ring because
its readers do not share one ring (the producer, the store and the gates
are r2, the CLI and MCP surfaces r4); the typed carrier itself lives in the
model store (``canonical.comparison_state``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

# -- why a comparison did not run ---------------------------------------------

NOT_COMPARED_DISABLED: Final = "disabled"
NOT_COMPARED_UNAVAILABLE: Final = "unavailable"
NOT_COMPARED_NOT_RUN: Final = "not_compared"
NotComparedReason = Literal["disabled", "unavailable", "not_compared"]
NOT_COMPARED_REASONS: Final[tuple[NotComparedReason, ...]] = (
    NOT_COMPARED_DISABLED,
    NOT_COMPARED_NOT_RUN,
    NOT_COMPARED_UNAVAILABLE,
)

# -- the comparisons and the deltas each one states ------------------------------

COMPARISON_CLONES: Final = "clones"
COMPARISON_HEALTH: Final = "health"
COMPARISON_ADOPTION: Final = "adoption"
COMPARISON_API_SURFACE: Final = "api_surface"
COMPARISON_COMPLEXITY: Final = "complexity"
COMPARISON_COUPLING: Final = "coupling"
COMPARISON_DEPENDENCIES: Final = "dependencies"
COMPARISON_DEAD_CODE: Final = "dead_code"

TERM_NEW_GROUPS: Final = "new_groups"
TERM_SCORE_DELTA: Final = "score_delta"
TERM_TYPING_PARAM_DELTA: Final = "typing_param_permille_delta"
TERM_TYPING_RETURN_DELTA: Final = "typing_return_permille_delta"
TERM_DOCSTRING_DELTA: Final = "docstring_permille_delta"
TERM_BREAKING_CHANGES: Final = "breaking_changes"
TERM_SIGNATURE_CHANGES: Final = "signature_changes"
TERM_ADDED_SYMBOLS: Final = "added_symbols"
TERM_NEW_HIGH_RISK: Final = "new_high_risk"
TERM_NEW_CYCLES: Final = "new_cycles"
TERM_NEW_IMPORT_CYCLES: Final = "new_import_cycles"
TERM_NEW_DEFERRED_CYCLES: Final = "new_deferred_cycles"
TERM_NEW_ITEMS: Final = "new_items"

#: Every comparison against the baseline a run states a delta of, with its
#: terms, in one fixed order.
COMPARISON_TERMS: Final[Mapping[str, tuple[str, ...]]] = {
    COMPARISON_CLONES: (TERM_NEW_GROUPS,),
    COMPARISON_HEALTH: (TERM_SCORE_DELTA,),
    COMPARISON_ADOPTION: (
        TERM_TYPING_PARAM_DELTA,
        TERM_TYPING_RETURN_DELTA,
        TERM_DOCSTRING_DELTA,
    ),
    COMPARISON_API_SURFACE: (
        TERM_BREAKING_CHANGES,
        TERM_SIGNATURE_CHANGES,
        TERM_ADDED_SYMBOLS,
    ),
    COMPARISON_COMPLEXITY: (TERM_NEW_HIGH_RISK,),
    COMPARISON_COUPLING: (TERM_NEW_HIGH_RISK,),
    COMPARISON_DEPENDENCIES: (
        TERM_NEW_CYCLES,
        TERM_NEW_IMPORT_CYCLES,
        TERM_NEW_DEFERRED_CYCLES,
    ),
    COMPARISON_DEAD_CODE: (TERM_NEW_ITEMS,),
}

#: The baseline lanes each comparison reads.  Health reads every lane its
#: score is derived from — the gate matrix's health manifest is this tuple
#: (``report.gates.evaluator.HEALTH_INPUT_LANES``); the clone comparison is
#: either clone lane.
COMPARISON_LANES: Final[Mapping[str, tuple[str, ...]]] = {
    COMPARISON_CLONES: ("clones.blocks", "clones.functions"),
    COMPARISON_HEALTH: (
        "clones.blocks",
        "clones.functions",
        "coupling_cohesion_observations",
        "dead_code",
        "dependencies",
        "module_identity",
        "risk_observations",
    ),
    COMPARISON_ADOPTION: ("adoption_counts",),
    COMPARISON_API_SURFACE: ("api_surface",),
    COMPARISON_COMPLEXITY: ("risk_observations",),
    COMPARISON_COUPLING: ("coupling_cohesion_observations",),
    COMPARISON_DEPENDENCIES: ("dependencies",),
    COMPARISON_DEAD_CODE: ("dead_code",),
}

ComparisonKey = tuple[str, str]

#: Every key of the state, in the fixed order of :data:`COMPARISON_TERMS`.
COMPARISON_KEYS: Final[tuple[ComparisonKey, ...]] = tuple(
    (comparison, term)
    for comparison, terms in COMPARISON_TERMS.items()
    for term in terms
)

#: How the report document spells each key: the metrics family and the key
#: of its ``summary`` that carries the delta, beside that family's
#: ``baseline_diff_available``.  The clone comparison has no family summary:
#: the document states it per group, as each group's novelty.
DOCUMENT_FIELDS: Final[Mapping[ComparisonKey, tuple[str, str]]] = {
    (COMPARISON_HEALTH, TERM_SCORE_DELTA): ("health", "delta"),
    (COMPARISON_ADOPTION, TERM_TYPING_PARAM_DELTA): (
        "coverage_adoption",
        "param_delta",
    ),
    (COMPARISON_ADOPTION, TERM_TYPING_RETURN_DELTA): (
        "coverage_adoption",
        "return_delta",
    ),
    (COMPARISON_ADOPTION, TERM_DOCSTRING_DELTA): (
        "coverage_adoption",
        "docstring_delta",
    ),
    (COMPARISON_API_SURFACE, TERM_BREAKING_CHANGES): ("api_surface", "breaking"),
    (COMPARISON_API_SURFACE, TERM_SIGNATURE_CHANGES): ("api_surface", "changed"),
    (COMPARISON_API_SURFACE, TERM_ADDED_SYMBOLS): ("api_surface", "added"),
    (COMPARISON_COMPLEXITY, TERM_NEW_HIGH_RISK): ("complexity", "new_high_risk"),
    (COMPARISON_COUPLING, TERM_NEW_HIGH_RISK): ("coupling", "new_high_risk"),
    (COMPARISON_DEPENDENCIES, TERM_NEW_CYCLES): ("dependencies", "new_cycles"),
    (COMPARISON_DEPENDENCIES, TERM_NEW_IMPORT_CYCLES): (
        "dependencies",
        "new_import_cycles",
    ),
    (COMPARISON_DEPENDENCIES, TERM_NEW_DEFERRED_CYCLES): (
        "dependencies",
        "new_deferred_cycles",
    ),
    (COMPARISON_DEAD_CODE, TERM_NEW_ITEMS): ("dead_code", "new_items"),
}


def not_compared_reason(*, enabled: bool, lanes_trusted: bool) -> NotComparedReason:
    """Why a comparison that did not run did not run: the one spelling the
    producer, the store reader and the document reader share."""
    if not enabled:
        return NOT_COMPARED_DISABLED
    if not lanes_trusted:
        return NOT_COMPARED_UNAVAILABLE
    return NOT_COMPARED_NOT_RUN


__all__ = [
    "COMPARISON_ADOPTION",
    "COMPARISON_API_SURFACE",
    "COMPARISON_CLONES",
    "COMPARISON_COMPLEXITY",
    "COMPARISON_COUPLING",
    "COMPARISON_DEAD_CODE",
    "COMPARISON_DEPENDENCIES",
    "COMPARISON_HEALTH",
    "COMPARISON_KEYS",
    "COMPARISON_LANES",
    "COMPARISON_TERMS",
    "DOCUMENT_FIELDS",
    "NOT_COMPARED_DISABLED",
    "NOT_COMPARED_NOT_RUN",
    "NOT_COMPARED_REASONS",
    "NOT_COMPARED_UNAVAILABLE",
    "TERM_ADDED_SYMBOLS",
    "TERM_BREAKING_CHANGES",
    "TERM_DOCSTRING_DELTA",
    "TERM_NEW_CYCLES",
    "TERM_NEW_DEFERRED_CYCLES",
    "TERM_NEW_GROUPS",
    "TERM_NEW_HIGH_RISK",
    "TERM_NEW_IMPORT_CYCLES",
    "TERM_NEW_ITEMS",
    "TERM_SCORE_DELTA",
    "TERM_SIGNATURE_CHANGES",
    "TERM_TYPING_PARAM_DELTA",
    "TERM_TYPING_RETURN_DELTA",
    "ComparisonKey",
    "NotComparedReason",
    "not_compared_reason",
]
