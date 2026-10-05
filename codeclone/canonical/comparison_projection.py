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

**Not compared -> null** (the maintainer's ruling, 2026-10-03, extended
2026-10-05): ``0`` means a measured comparison result equal to zero; if no
comparison happened, ``0`` is a false statement.  Whether a comparison ran
is the run's normalized comparison state
(``contracts.comparison_state.ComparisonState``), decided once by the
producer (``core.comparison_state``) and written into the document and,
through it, into the store's rows.  This module reads it back off the rows
(:func:`stored_comparison_state`) and applies it to the nine comparison
fields of ``get_run_summary`` (:data:`SUMMARY_COMPARISON_FIELDS`,
:func:`answered_if_compared`); the memory answer reads the same state off
the sealed document (``contracts.comparison_state.document_comparison_state``)
and applies the same rule, so the two answers cannot disagree about a cell.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from itertools import chain
from typing import Final

from codeclone.canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    DELTA_FAMILY_TERMS,
    LANE_TRUSTED,
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNAVAILABLE,
    FindingNoveltyRow,
)
from codeclone.canonical.comparison_state import (
    ComparisonResult,
    ComparisonState,
    comparison_results,
    comparison_state,
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
from codeclone.contracts.comparison_state import (
    COMPARISON_ADOPTION,
    COMPARISON_API_SURFACE,
    COMPARISON_CLONES,
    COMPARISON_COMPLEXITY,
    COMPARISON_COUPLING,
    COMPARISON_DEAD_CODE,
    COMPARISON_DEPENDENCIES,
    COMPARISON_HEALTH,
    COMPARISON_LANES,
    COMPARISON_TERMS,
    TERM_ADDED_SYMBOLS,
    TERM_BREAKING_CHANGES,
    TERM_NEW_CYCLES,
    TERM_NEW_DEFERRED_CYCLES,
    TERM_NEW_GROUPS,
    TERM_NEW_IMPORT_CYCLES,
    TERM_SCORE_DELTA,
    TERM_SIGNATURE_CHANGES,
    ComparisonKey,
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
    if _compared_lanes(comparison).isdisjoint(COMPARISON_LANES[COMPARISON_CLONES]):
        return None
    return _new_count(comparison.clone_novelty)


def metric_deltas(comparison: ComparisonFacts) -> dict[str, int]:
    """The six ``diff`` delta terms in the surface's order.  A family whose
    comparison did not run has no rows and reads ``0`` here; the run
    summary answers those terms ``None`` (:func:`answered_if_compared`)."""
    values = {
        row.delta: row.value
        for row in chain(comparison.adoption_delta, comparison.api_surface_delta)
    }
    return {key: values.get(key, 0) for key in DIFF_DELTA_KEYS}


# -- Not compared -> null: the state, read off the rows ----------------------------

#: The two blocks of the run summary that carry comparison fields.
SUMMARY_DIFF_BLOCK: Final = "diff"
SUMMARY_HEALTH_BLOCK: Final = "health"

#: How the run summary spells the comparison keys it states: the eight terms
#: of ``diff`` and ``health.delta``.
SUMMARY_COMPARISON_FIELDS: Final[Mapping[tuple[str, str], ComparisonKey]] = {
    (SUMMARY_DIFF_BLOCK, "new_clones"): (COMPARISON_CLONES, TERM_NEW_GROUPS),
    (SUMMARY_DIFF_BLOCK, "health_delta"): (COMPARISON_HEALTH, TERM_SCORE_DELTA),
    **{
        (SUMMARY_DIFF_BLOCK, term): (COMPARISON_ADOPTION, term)
        for term in DELTA_FAMILY_TERMS["adoption_delta"]
    },
    (SUMMARY_DIFF_BLOCK, "api_breaking_changes"): (
        COMPARISON_API_SURFACE,
        TERM_BREAKING_CHANGES,
    ),
    (SUMMARY_DIFF_BLOCK, "api_signature_changes"): (
        COMPARISON_API_SURFACE,
        TERM_SIGNATURE_CHANGES,
    ),
    (SUMMARY_DIFF_BLOCK, "new_api_symbols"): (
        COMPARISON_API_SURFACE,
        TERM_ADDED_SYMBOLS,
    ),
    (SUMMARY_HEALTH_BLOCK, "delta"): (COMPARISON_HEALTH, TERM_SCORE_DELTA),
}

#: The API delta rows of the house, by the state's term.
_API_DELTA_TERMS: Final[Mapping[str, str]] = {
    TERM_BREAKING_CHANGES: "api_breaking_changes",
    TERM_SIGNATURE_CHANGES: "api_signature_changes",
    TERM_ADDED_SYMBOLS: "new_api_symbols",
}

_DEFERRED_CYCLE: Final = "deferred_cycle"
_IMPORT_CYCLE: Final = "import_cycle"


def _new_count(rows: Collection[FindingNoveltyRow]) -> int:
    return sum(1 for row in rows if row.novelty == NOVELTY_NEW)


def _cycle_values(model: CanonicalModel) -> dict[str, int]:
    """The dependency terms off the cycle novelty rows, split by the kind
    the published dependency finding states."""
    kinds = {
        str(group["id"]): group.get("kind")
        for group in projected_finding_groups(model)["design"]
        if group.get("category") == "dependency"
    }
    new = [
        row.finding_id
        for row in model.facts.comparison.dependency_cycle_novelty
        if row.novelty == NOVELTY_NEW
    ]
    return {
        TERM_NEW_CYCLES: len(new),
        TERM_NEW_IMPORT_CYCLES: sum(
            1 for item in new if kinds.get(item) == _IMPORT_CYCLE
        ),
        TERM_NEW_DEFERRED_CYCLES: sum(
            1 for item in new if kinds.get(item) == _DEFERRED_CYCLE
        ),
    }


def _stored_values(model: CanonicalModel, name: str) -> dict[str, int]:
    """The terms one comparison that ran states, off its rows."""
    comparison = model.facts.comparison
    deltas = metric_deltas(comparison)
    if name == COMPARISON_CLONES:
        return {TERM_NEW_GROUPS: _new_count(comparison.clone_novelty)}
    if name == COMPARISON_HEALTH:
        return {TERM_SCORE_DELTA: next(row.value for row in comparison.health_delta)}
    if name == COMPARISON_ADOPTION:
        return {term: deltas[term] for term in COMPARISON_TERMS[name]}
    if name == COMPARISON_API_SURFACE:
        return {term: deltas[key] for term, key in _API_DELTA_TERMS.items()}
    if name == COMPARISON_DEPENDENCIES:
        return _cycle_values(model)
    novelty = {
        COMPARISON_COMPLEXITY: comparison.complexity_novelty,
        COMPARISON_COUPLING: comparison.coupling_novelty,
        COMPARISON_DEAD_CODE: comparison.dead_symbol_novelty,
    }[name]
    (term,) = COMPARISON_TERMS[name]
    return {term: _new_count(novelty)}


def stored_comparison_state(model: CanonicalModel) -> ComparisonState:
    """The normalized comparison state one stored run states, read off its
    rows: a lane comparison ran when its availability row says
    ``compared`` (either lane, for clones), the health comparison when its
    ``health_delta`` row exists; the reason is named off the disabled
    capabilities and the lane trust rows by the one rule
    (``contracts.comparison_state.not_compared_reason``)."""
    comparison = model.facts.comparison
    compared_lanes = _compared_lanes(comparison)
    disabled = {row.lane for row in comparison.disabled_capabilities}
    trusted = {row.lane for row in comparison.lane_trust if row.status == LANE_TRUSTED}
    results: dict[ComparisonKey, ComparisonResult] = {}
    for name, lanes in COMPARISON_LANES.items():
        if name == COMPARISON_CLONES:
            ran = not compared_lanes.isdisjoint(lanes)
            enabled = not disabled.issuperset(lanes)
            lanes_trusted = not trusted.isdisjoint(lanes)
        else:
            ran = (
                bool(comparison.health_delta)
                if name == COMPARISON_HEALTH
                else compared_lanes.issuperset(lanes)
            )
            enabled = disabled.isdisjoint(lanes)
            lanes_trusted = trusted.issuperset(lanes)
        results.update(
            comparison_results(
                name,
                _stored_values(model, name) if ran else {},
                ran=ran,
                enabled=enabled,
                lanes_trusted=lanes_trusted,
            )
        )
    return comparison_state(results)


def answered_if_compared(
    block: str, values: Mapping[str, object], state: ComparisonState
) -> dict[str, object]:
    """One block of the run summary with every comparison field whose
    comparison this run did not make answered ``None``.

    The decision reads the state -- the producer's, as the answer's own
    carrier states it -- and never the value: a measured zero stays ``0``,
    and a number the run never measured is ``None`` whatever it is.  Every
    other key of the block is its own, unchanged and in its order.
    """
    answered: dict[str, object] = {}
    for key, value in values.items():
        field = SUMMARY_COMPARISON_FIELDS.get((block, key))
        if field is not None and not state.result(*field).is_compared:
            answered[key] = None
        else:
            answered[key] = value
    return answered


__all__ = [
    "DIFF_DELTA_KEYS",
    "SOURCE_KIND_BREAKDOWN",
    "SUMMARY_COMPARISON_FIELDS",
    "SUMMARY_DIFF_BLOCK",
    "SUMMARY_HEALTH_BLOCK",
    "UNPROJECTED_BASELINE_KEYS",
    "UNPROJECTED_DIFF_KEYS",
    "answered_if_compared",
    "baseline_state",
    "group_novelty",
    "known_debt_paths",
    "metric_deltas",
    "metrics_baseline_state",
    "new_by_source_kind",
    "new_clone_groups",
    "new_finding_paths",
    "novelty_counts",
    "stored_comparison_state",
]
