# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The comparison-tier fields of the MCP answers, rebuilt from canonical
rows — one owner.

Canonical epoch E2 (2026-09-27).  The comparison house
(``ComparisonFacts``) carries the baseline witnesses, the per-lane
availability, the novelty of every governed finding and the metric deltas
as run-store rows.  This module answers, from those rows alone (plus the
analysis skeletons of ``finding_projection`` for the finding universe), the
fields serving census 3 assigns to the comparison tier — in the surface's
own key order, so a shadow pin can hold each against the surface's answer
byte for byte.  The surface is the oracle and the store the shadow: nothing
here is read by a surface (the read edge and the cutover are later waves).

**What is projected**: ``baseline`` / ``metrics_baseline`` (Cmp1/Cmp2, off
the two witnesses), ``findings.new/known/unavailable`` and
``new_by_source_kind`` (Cmp4 over the published finding universe),
``diff.new_clones`` (Cmp4 under the Cmp7 availability of the clone lanes),
the six ``diff`` deltas (Cmp5), the ids and sites of the findings the
comparison called new, and the paths the comparison calls known debt.

**What is NOT projected**, named so it cannot rot: ``runtime_python_tag``
and ``interpreter_provenance`` are execution (the interpreter that ran, not
the container compared against — a runtime tag among a run's rows would
split one report identity into two store runs); ``diff.health_delta`` is
evaluation; ``novelty_reason`` is stored and held by the model laws, but no
census row reads it, and the authority family's reason is a document
literal with no comparison term.  Run-against-run facts (``compare_runs``,
the PR summary's ``resolved``, the patch contract's structural delta) are
not comparisons against a baseline and belong to a later wave.

**Not compared -> null** (the maintainer's ruling, 2026-10-03): ``0`` means
a measured comparison result equal to zero; if no comparison happened, ``0``
is a false statement.  The nine comparison fields of ``get_run_summary``
(:data:`SUMMARY_COMPARISON_FIELDS`) state a number only when their
comparison ran, and ``None`` otherwise.  This module is the one owner of
that decision for both answers: :func:`answered_if_compared` applies it,
and it reads which comparisons ran -- never a value -- from the carrier
each answer is built from: the store's rows (:func:`comparisons_made`) or
the sealed report document the memory answer is built from
(:func:`document_comparisons_made`).  Both read the same producer decision
(``core.reporting`` writes ``baseline_diff_available`` per family and
``core.comparison_snapshot`` turns that same flag into the availability
row), so the two answers cannot disagree about a cell.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from itertools import chain
from typing import Final

from codeclone.canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    CLONE_KIND_LANES,
    COMPARISON_LANE_FAMILIES,
    DELTA_FAMILY_TERMS,
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNAVAILABLE,
)
from codeclone.canonical.finding_projection import (
    PROJECTED_FAMILIES,
    projected_finding_groups,
)
from codeclone.canonical.model import (
    CanonicalModel,
    ComparisonFacts,
    novelty_families,
)
from codeclone.domain.source_scope import SOURCE_KIND_ORDER
from codeclone.utils.coerce import as_mapping, as_sequence

#: The ``baseline`` keys the surface answers that the store does not, by
#: the tier they belong to.
UNPROJECTED_BASELINE_KEYS: Final[Mapping[str, str]] = {
    "runtime_python_tag": "execution",
    "interpreter_provenance": "execution",
}

#: The ``diff`` key the surface answers that is not a comparison fact.
UNPROJECTED_DIFF_KEYS: Final[Mapping[str, str]] = {"health_delta": "evaluation"}

#: The six delta terms of the surface's ``diff`` block, in its key order
#: (the terms themselves are ``comparison_rows.DELTA_FAMILY_TERMS``; a pin
#: holds the two sets equal).
DIFF_DELTA_KEYS: Final[tuple[str, ...]] = (
    "typing_param_permille_delta",
    "typing_return_permille_delta",
    "docstring_permille_delta",
    "api_breaking_changes",
    "api_signature_changes",
    "new_api_symbols",
)

#: The source-kind breakdown in the domain's own order (production, tests,
#: fixtures, mixed, other) — the order the surface's breakdown is built in.
SOURCE_KIND_BREAKDOWN: Final[tuple[str, ...]] = tuple(
    sorted(SOURCE_KIND_ORDER, key=SOURCE_KIND_ORDER.__getitem__)
)

_NOVELTY_COUNT_KEYS: Final[tuple[str, ...]] = (
    NOVELTY_NEW,
    NOVELTY_KNOWN,
    NOVELTY_UNAVAILABLE,
)


# -- Cmp1 / Cmp2: the two witnesses -------------------------------------------


def baseline_state(comparison: ComparisonFacts) -> dict[str, object]:
    """``baseline`` of ``get_run_summary`` / ``get_production_triage``,
    off the clone-baseline witness, without the two execution keys.

    ``trusted`` is ``loaded``: both baseline resolvers set
    ``trusted_for_diff`` exactly when they set ``loaded``
    (``BaselineWitnessRecord``), and the shadow pin holds that on a trusted,
    a refused and a missing container.  ``baseline_python_tag`` is the
    artifact's provenance and is stated only when the artifact names one,
    as the surface does.  An unwitnessed house answers the empty block.
    """
    witness = comparison.baseline_witness
    if witness is None:
        return {}
    payload: dict[str, object] = {
        "loaded": witness.loaded,
        "status": witness.status,
        "trusted": witness.loaded,
        "compared_without_valid_baseline": not witness.loaded,
    }
    if witness.python_tag is not None and witness.python_tag.strip():
        payload["baseline_python_tag"] = witness.python_tag
    return payload


def metrics_baseline_state(comparison: ComparisonFacts) -> dict[str, object]:
    """``metrics_baseline``: off the metrics-baseline witness, ``trusted``
    by the same one rule as the clone baseline's."""
    witness = comparison.metrics_baseline_witness
    if witness is None:
        return {}
    return {
        "loaded": witness.loaded,
        "status": witness.status,
        "trusted": witness.loaded,
    }


# -- Cmp4: novelty over the published finding universe -------------------------


def _published_groups(model: CanonicalModel) -> Iterator[Mapping[str, object]]:
    groups = projected_finding_groups(model)
    for family in PROJECTED_FAMILIES:
        yield from groups[family]


def _novelty_by_id(comparison: ComparisonFacts) -> dict[str, str]:
    return {
        row.finding_id: row.novelty
        for _name, rows in novelty_families(comparison)
        for row in rows
    }


def _worded_groups(
    model: CanonicalModel,
) -> Iterator[tuple[Mapping[str, object], str]]:
    """Every published group with its novelty word: a group no novelty row
    names is ``unavailable`` — no comparison term reached it."""
    novelty = _novelty_by_id(model.facts.comparison)
    for group in _published_groups(model):
        yield group, novelty.get(str(group["id"]), NOVELTY_UNAVAILABLE)


def group_novelty(model: CanonicalModel) -> dict[str, str]:
    """The novelty word of every published finding, by id."""
    return {str(group["id"]): word for group, word in _worded_groups(model)}


def novelty_counts(model: CanonicalModel) -> dict[str, int]:
    """``findings.new`` / ``known`` / ``unavailable``: one count per
    published group (two groups may share one id), three buckets that
    always sum to the finding total."""
    counts = dict.fromkeys(_NOVELTY_COUNT_KEYS, 0)
    for _group, word in _worded_groups(model):
        counts[word] += 1
    return counts


def new_by_source_kind(model: CanonicalModel) -> dict[str, int]:
    """``findings.new_by_source_kind``: the new findings by the dominant
    source kind of their sites (an analysis fact of the skeleton)."""
    breakdown = dict.fromkeys(SOURCE_KIND_BREAKDOWN, 0)
    for group, word in _worded_groups(model):
        if word == NOVELTY_NEW:
            kind = str(as_mapping(group.get("source_scope")).get("dominant_kind"))
            breakdown[kind] += 1
    return breakdown


def _group_paths(group: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(as_mapping(item).get("relative_path", ""))
                for item in as_sequence(group.get("items"))
            }
            - {""}
        )
    )


def new_finding_paths(model: CanonicalModel) -> dict[str, tuple[str, ...]]:
    """The findings the comparison called new, by id, with the paths of
    their sites — the PR summary's ``new_findings_in_changed_files`` is the
    subset whose sites touch the changed paths."""
    return {
        str(group["id"]): _group_paths(group)
        for group, word in _worded_groups(model)
        if word == NOVELTY_NEW
    }


def known_debt_paths(model: CanonicalModel) -> tuple[str, ...]:
    """Every path a finding the comparison called ``known`` sits in — the
    set the blast radius's ``known_baseline_debt`` review context is cut
    from (the zone and the origin are the blast radius's own)."""
    return tuple(
        sorted(
            {
                path
                for group, word in _worded_groups(model)
                if word == NOVELTY_KNOWN
                for path in _group_paths(group)
            }
        )
    )


# -- Cmp4 under Cmp7, and Cmp5: the ``diff`` block ---------------------------------


def _compared_lanes(comparison: ComparisonFacts) -> frozenset[str]:
    """The lanes whose comparison ran, as the availability rows state it."""
    return frozenset(
        row.lane
        for row in comparison.comparison_availability
        if row.availability == AVAILABILITY_COMPARED
    )


def new_clone_groups(comparison: ComparisonFacts) -> int | None:
    """``diff.new_clones``: ``None`` when no clone lane was compared (not a
    zero the run never measured), else the new clone groups."""
    if COMPARISON_CLONES not in comparisons_made(comparison):
        return None
    return sum(1 for row in comparison.clone_novelty if row.novelty == NOVELTY_NEW)


def metric_deltas(comparison: ComparisonFacts) -> dict[str, int]:
    """The six ``diff`` delta terms in the surface's order.  A family whose
    comparison did not run has no rows and reads ``0`` here; the run
    summary answers those terms ``None`` (:func:`answered_if_compared`)."""
    values = {
        row.delta: row.value
        for row in chain(comparison.adoption_delta, comparison.api_surface_delta)
    }
    return {key: values.get(key, 0) for key in DIFF_DELTA_KEYS}


# -- Not compared -> null: the one owner of the decision ----------------------------

#: The comparisons whose results the run summary states.  The adoption and
#: API comparisons are named by their lane (an availability row of the
#: comparison house); the clone comparison is either clone lane; the health
#: comparison is the health score's delta, which the house states by the
#: presence of its ``health_delta`` row (no availability row carries it).
COMPARISON_CLONES: Final = "clones"
COMPARISON_ADOPTION: Final = "adoption_counts"
COMPARISON_API_SURFACE: Final = "api_surface"
COMPARISON_HEALTH: Final = "health"

#: The two blocks of the run summary that carry comparison fields.
SUMMARY_DIFF_BLOCK: Final = "diff"
SUMMARY_HEALTH_BLOCK: Final = "health"

#: The report document's metrics family whose ``baseline_diff_available``
#: states the health comparison (``core.reporting._metrics_for_report``).
_HEALTH_FAMILY: Final = "health"

#: The lane whose comparison states each metric delta family -- the pairing
#: both comparison producers write (a pin holds it equal to theirs).
_DELTA_FAMILY_COMPARISONS: Final[Mapping[str, str]] = {
    "adoption_delta": COMPARISON_ADOPTION,
    "api_surface_delta": COMPARISON_API_SURFACE,
}

#: Every comparison field of ``get_run_summary``, as (block, key), and the
#: comparison whose result it states: the eight terms of ``diff`` and
#: ``health.delta``.
SUMMARY_COMPARISON_FIELDS: Final[Mapping[tuple[str, str], str]] = {
    (SUMMARY_DIFF_BLOCK, "new_clones"): COMPARISON_CLONES,
    (SUMMARY_DIFF_BLOCK, "health_delta"): COMPARISON_HEALTH,
    **{
        (SUMMARY_DIFF_BLOCK, term): comparison
        for family, comparison in _DELTA_FAMILY_COMPARISONS.items()
        for term in DELTA_FAMILY_TERMS[family]
    },
    (SUMMARY_HEALTH_BLOCK, "delta"): COMPARISON_HEALTH,
}


def _made(*, lanes: Collection[str], clones: bool, health: bool) -> frozenset[str]:
    made = {
        comparison
        for comparison in _DELTA_FAMILY_COMPARISONS.values()
        if comparison in lanes
    }
    if clones:
        made.add(COMPARISON_CLONES)
    if health:
        made.add(COMPARISON_HEALTH)
    return frozenset(made)


def comparisons_made(comparison: ComparisonFacts) -> frozenset[str]:
    """The comparisons one stored run made, off its rows: a lane whose
    availability row says ``compared`` (the model law holds its delta rows
    present exactly then), either clone lane compared, and the health
    comparison when its ``health_delta`` row exists."""
    lanes = _compared_lanes(comparison)
    return _made(
        lanes=lanes,
        clones=not lanes.isdisjoint(CLONE_KIND_LANES.values()),
        health=bool(comparison.health_delta),
    )


def _family_compared(document: Mapping[str, object], family: str) -> bool:
    families = as_mapping(as_mapping(document.get("metrics")).get("families"))
    summary = as_mapping(as_mapping(families.get(family)).get("summary"))
    return summary.get("baseline_diff_available") is True


def document_comparisons_made(
    document: Mapping[str, object], *, clones_compared: bool
) -> frozenset[str]:
    """The comparisons one run made, off the sealed report document its
    memory answer is built from -- the two facts the producer turns into an
    availability row: a metric lane's comparison ran when the lane is not a
    disabled capability of the run (``baseline.disabled_capabilities``) and
    its family says ``baseline_diff_available: true``; the health
    comparison when the health family says so (the flag the health delta
    row is written from).  A disabled lane is never compared, whatever its
    family says: measured 2026-10-05, a run with the API lane not enabled
    publishes ``api_surface.summary.baseline_diff_available: true`` beside
    ``enabled: false``.  The clone comparison is the caller's own record of
    it (``clones_compared``): the document states it per group, and cannot
    state a trusted clone lane that was not compared when no group exists."""
    disabled = {
        str(lane)
        for lane in as_sequence(
            as_mapping(document.get("baseline")).get("disabled_capabilities")
        )
    }
    lanes = {
        lane
        for lane in _DELTA_FAMILY_COMPARISONS.values()
        if lane not in disabled
        and _family_compared(document, COMPARISON_LANE_FAMILIES[lane])
    }
    return _made(
        lanes=lanes,
        clones=clones_compared,
        health=_family_compared(document, _HEALTH_FAMILY),
    )


def answered_if_compared(
    block: str, values: Mapping[str, object], made: Collection[str]
) -> dict[str, object]:
    """One block of the run summary with every comparison field whose
    comparison this run did not make answered ``None``.

    The decision reads ``made`` -- the comparisons that ran, as the answer's
    own carrier states them -- and never the value: a measured zero stays
    ``0``, and a number the run never measured is ``None`` whatever it is.
    Every other key of the block is its own, unchanged and in its order.
    """
    answered: dict[str, object] = {}
    for key, value in values.items():
        comparison = SUMMARY_COMPARISON_FIELDS.get((block, key))
        if comparison is not None and comparison not in made:
            answered[key] = None
        else:
            answered[key] = value
    return answered


__all__ = [
    "COMPARISON_ADOPTION",
    "COMPARISON_API_SURFACE",
    "COMPARISON_CLONES",
    "COMPARISON_HEALTH",
    "DIFF_DELTA_KEYS",
    "SOURCE_KIND_BREAKDOWN",
    "SUMMARY_COMPARISON_FIELDS",
    "SUMMARY_DIFF_BLOCK",
    "SUMMARY_HEALTH_BLOCK",
    "UNPROJECTED_BASELINE_KEYS",
    "UNPROJECTED_DIFF_KEYS",
    "answered_if_compared",
    "baseline_state",
    "comparisons_made",
    "document_comparisons_made",
    "group_novelty",
    "known_debt_paths",
    "metric_deltas",
    "metrics_baseline_state",
    "new_by_source_kind",
    "new_clone_groups",
    "new_finding_paths",
    "novelty_counts",
]
