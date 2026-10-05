# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The typed carrier of a run's normalized comparison state.

Every comparison delta a run states is ``compared(value)`` or
``not_compared(reason)``, keyed by ``(comparison, term)``
(``contracts.comparison_state``: the keys, the reasons, the lanes each
comparison reads, the report document's spelling, and the one rule naming a
reason).  The producer (``core.comparison_state.run_comparison_state``)
builds the state once per run and writes the report document from it; the
run store's rows are written off that document; this module reads the state
back off the document (:func:`document_comparison_state`), and
``canonical.comparison_projection.stored_comparison_state`` reads it back
off the rows.  A reader never decides again: it reads the producer's
``made`` -- the family's ``baseline_diff_available``, the availability row,
the health delta row -- and names the reason by the same rule.

It lives in the model store because its types are model definitions
(the dataclass placement law), and beside the store reader that uses it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from codeclone.contracts.comparison_state import (
    COMPARISON_CLONES,
    COMPARISON_KEYS,
    COMPARISON_LANES,
    COMPARISON_TERMS,
    DOCUMENT_FIELDS,
    TERM_NEW_GROUPS,
    ComparisonKey,
    NotComparedReason,
    not_compared_reason,
)
from codeclone.utils.coerce import as_mapping, as_sequence

# -- the typed result ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """``compared(value)`` or ``not_compared(reason)`` — never both, never
    neither.  Build it through :func:`compared` / :func:`not_compared`."""

    value: int | None
    reason: NotComparedReason | None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.reason is None):
            raise ValueError("a comparison result is a value or a reason, not both")

    @property
    def is_compared(self) -> bool:
        return self.reason is None


def compared(value: int) -> ComparisonResult:
    """A comparison that ran; ``0`` is its measured zero."""
    return ComparisonResult(value=int(value), reason=None)


def not_compared(reason: NotComparedReason) -> ComparisonResult:
    """A comparison that did not run, and why."""
    return ComparisonResult(value=None, reason=reason)


def comparison_results(
    comparison: str,
    values: Mapping[str, int],
    *,
    ran: bool,
    enabled: bool,
    lanes_trusted: bool,
) -> dict[ComparisonKey, ComparisonResult]:
    """Every term of one comparison: its value when the comparison ran, else
    the reason.  ``ran`` alone decides; ``enabled`` and ``lanes_trusted``
    only name the reason (a capability the run did not enable never ran)."""
    terms = COMPARISON_TERMS[comparison]
    if ran and enabled:
        return {(comparison, term): compared(values[term]) for term in terms}
    reason = not_compared_reason(enabled=enabled, lanes_trusted=lanes_trusted)
    return {(comparison, term): not_compared(reason) for term in terms}


# -- the state -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComparisonState:
    """One result per :data:`COMPARISON_KEYS` entry, exactly."""

    results: Mapping[ComparisonKey, ComparisonResult]

    def __post_init__(self) -> None:
        if set(self.results) != set(COMPARISON_KEYS):
            raise ValueError("a comparison state states every comparison key")

    def result(self, comparison: str, term: str) -> ComparisonResult:
        return self.results[(comparison, term)]

    def value(self, comparison: str, term: str) -> int | None:
        """The delta, or ``None`` when its comparison did not run."""
        return self.results[(comparison, term)].value

    def made(self, comparison: str) -> bool:
        """Whether the comparison ran (all of its terms are compared)."""
        return all(
            self.results[(comparison, term)].is_compared
            for term in COMPARISON_TERMS[comparison]
        )

    def reason(self, comparison: str) -> NotComparedReason | None:
        """Why the comparison did not run, ``None`` when it ran."""
        return self.results[(comparison, COMPARISON_TERMS[comparison][0])].reason

    def comparisons_made(self) -> frozenset[str]:
        return frozenset(
            comparison for comparison in COMPARISON_TERMS if self.made(comparison)
        )


def comparison_state(
    results: Mapping[ComparisonKey, ComparisonResult],
) -> ComparisonState:
    return ComparisonState(
        results={key: results[key] for key in COMPARISON_KEYS},
    )


# -- the report document's spelling of the state -----------------------------------


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def document_comparison_state(
    document: Mapping[str, object],
    *,
    new_clone_groups: object,
) -> ComparisonState:
    """The state a sealed report document states, read back — never decided
    again.  A family's ``baseline_diff_available`` is the producer's
    ``made``, its delta keys the producer's values; the reason is named off
    the document's own baseline section (``disabled_capabilities`` and
    ``sorted_lane_trust``) by :func:`not_compared_reason`.  The clone
    comparison is the caller's record of it, ``new_clone_groups``: ``None``
    when no clone lane was compared, else the new groups -- the document
    states it per group, and cannot state a trusted clone lane that ran and
    found no group."""
    baseline = as_mapping(document.get("baseline"))
    disabled = frozenset(
        str(lane) for lane in as_sequence(baseline.get("disabled_capabilities"))
    )
    trusted = frozenset(
        str(as_mapping(row).get("name"))
        for row in as_sequence(baseline.get("sorted_lane_trust"))
        if as_mapping(row).get("status") == "trusted"
    )
    families = as_mapping(as_mapping(document.get("metrics")).get("families"))
    results: dict[ComparisonKey, ComparisonResult] = {}
    for comparison, terms in COMPARISON_TERMS.items():
        lanes = COMPARISON_LANES[comparison]
        if comparison == COMPARISON_CLONES:
            ran = new_clone_groups is not None
            enabled = not set(lanes) <= disabled
            lanes_trusted = not trusted.isdisjoint(lanes)
            values = {TERM_NEW_GROUPS: _int(new_clone_groups)}
        else:
            family = DOCUMENT_FIELDS[(comparison, terms[0])][0]
            summary = as_mapping(as_mapping(families.get(family)).get("summary"))
            ran = summary.get("baseline_diff_available") is True
            enabled = disabled.isdisjoint(lanes)
            lanes_trusted = trusted.issuperset(lanes)
            values = {
                term: _int(summary.get(DOCUMENT_FIELDS[(comparison, term)][1]))
                for term in terms
            }
        results.update(
            comparison_results(
                comparison,
                values,
                ran=ran,
                enabled=enabled,
                lanes_trusted=lanes_trusted,
            )
        )
    return comparison_state(results)


__all__ = [
    "ComparisonResult",
    "ComparisonState",
    "compared",
    "comparison_results",
    "comparison_state",
    "document_comparison_state",
    "not_compared",
]
