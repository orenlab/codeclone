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
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import chain
from typing import Final

from codeclone.canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    CLONE_KIND_LANES,
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


def new_clone_groups(comparison: ComparisonFacts) -> int | None:
    """``diff.new_clones``: ``None`` when no clone lane was compared (not a
    zero the run never measured), else the new clone groups."""
    compared = {
        row.lane
        for row in comparison.comparison_availability
        if row.availability == AVAILABILITY_COMPARED
    }
    if compared.isdisjoint(CLONE_KIND_LANES.values()):
        return None
    return sum(1 for row in comparison.clone_novelty if row.novelty == NOVELTY_NEW)


def metric_deltas(comparison: ComparisonFacts) -> dict[str, int]:
    """The six ``diff`` delta terms in the surface's order.  A family whose
    comparison did not run has no rows; the surface answers ``0`` for its
    terms, and so does the projection."""
    values = {
        row.delta: row.value
        for row in chain(comparison.adoption_delta, comparison.api_surface_delta)
    }
    return {key: values.get(key, 0) for key in DIFF_DELTA_KEYS}


__all__ = [
    "DIFF_DELTA_KEYS",
    "SOURCE_KIND_BREAKDOWN",
    "UNPROJECTED_BASELINE_KEYS",
    "UNPROJECTED_DIFF_KEYS",
    "baseline_state",
    "group_novelty",
    "known_debt_paths",
    "metric_deltas",
    "metrics_baseline_state",
    "new_by_source_kind",
    "new_clone_groups",
    "new_finding_paths",
    "novelty_counts",
]
