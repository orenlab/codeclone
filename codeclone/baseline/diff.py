# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence, Set

from ..metrics.api_surface import compare_api_surfaces
from ..models import (
    ApiBreakingChange,
    ApiSurfaceSnapshot,
    DependencyCycleDiff,
    DependencyCycleFact,
    DependencyCycleKind,
    DependencyCycleKindChange,
    MetricsDiff,
    MetricsSnapshot,
)


def diff_clone_groups(
    *,
    known_functions: Set[str],
    known_blocks: Set[str],
    func_groups: Mapping[str, object],
    block_groups: Mapping[str, object],
) -> tuple[set[str], set[str]]:
    new_funcs = set(func_groups.keys()) - known_functions
    new_blocks = set(block_groups.keys()) - known_blocks
    return new_funcs, new_blocks


def _kind_by_members(
    facts: Sequence[DependencyCycleFact],
) -> dict[tuple[str, ...], DependencyCycleKind]:
    # Sorted so that a member set carrying two kinds — which the classifier
    # cannot produce, but a hand-built snapshot could — resolves the same way
    # on every run instead of depending on iteration order.
    return {fact.modules: fact.kind for fact in sorted(facts, key=_fact_key)}


def _fact_key(fact: DependencyCycleFact) -> tuple[tuple[str, ...], str]:
    return (fact.modules, fact.kind)


def _diff_cycles(
    *,
    baseline: Sequence[DependencyCycleFact],
    current: Sequence[DependencyCycleFact],
) -> DependencyCycleDiff:
    """Compare two runs' cycles as (members, kind), never as members alone.

    Three questions, three answers, because collapsing them loses the fact
    that made the kind worth classifying:

    * ``new_cycles`` — these modules did not cycle before. The visibility lane;
      deferred entries belong here and must still be reported.
    * ``new_import_cycles`` — a crash-at-import risk exists now and did not
      before. True both for a brand-new import cycle and for a deferred cycle
      that hardened into one, so it is not a subset of ``new_cycles``. This is
      the only cycle lane that gates.
    * ``cycle_kind_changes`` — the members still cycle but the law now reads
      them differently. Without this a deferred cycle turning critical, and an
      import cycle repaired into a deferred one, would both read as
      "unchanged": one count in, one count out.
    """

    baseline_kinds = _kind_by_members(baseline)
    current_kinds = _kind_by_members(current)
    new_members = sorted(set(current_kinds) - set(baseline_kinds))
    return DependencyCycleDiff(
        new_cycles=tuple(new_members),
        new_import_cycles=tuple(
            sorted(
                members
                for members, kind in current_kinds.items()
                if kind == "import_cycle"
                and baseline_kinds.get(members) != "import_cycle"
            )
        ),
        new_deferred_cycles=tuple(
            members
            for members in new_members
            if current_kinds[members] == "deferred_cycle"
        ),
        cycle_kind_changes=tuple(
            DependencyCycleKindChange(
                modules=members,
                previous_kind=baseline_kinds[members],
                current_kind=current_kinds[members],
            )
            for members in sorted(set(current_kinds) & set(baseline_kinds))
            if baseline_kinds[members] != current_kinds[members]
        ),
    )


def _health_delta(*, baseline: int | None, current: int | None) -> int:
    """Subtract two health scores, or report no movement when one is absent.

    A missing score on either side means no health comparison happened, so
    there is no difference to state. Zero is what this repository already
    publishes for a comparison that did not run -- the report writes it beside
    ``baseline_diff_available: false``, which is the fact that keeps it apart
    from "compared, unchanged" (`RP2`, `G4`). Subtracting against an absent
    score instead would manufacture the whole of the present score as movement.
    """

    if baseline is None or current is None:
        return 0
    return current - baseline


def diff_metrics(
    *,
    baseline_snapshot: MetricsSnapshot | None,
    current_snapshot: MetricsSnapshot,
    baseline_api_surface: ApiSurfaceSnapshot | None,
    current_api_surface: ApiSurfaceSnapshot | None,
) -> MetricsDiff:
    snapshot = baseline_snapshot or MetricsSnapshot(
        max_complexity=0,
        high_risk_functions=(),
        max_coupling=0,
        high_coupling_classes=(),
        max_cohesion=0,
        low_cohesion_classes=(),
        dependency_cycles=(),
        dependency_max_depth=0,
        dead_code_items=(),
        health_score=0,
        health_grade="F",
        typing_param_permille=0,
        typing_return_permille=0,
        docstring_permille=0,
        typing_any_count=0,
    )

    new_high_risk_functions = tuple(
        sorted(
            set(current_snapshot.high_risk_functions)
            - set(snapshot.high_risk_functions)
        )
    )
    new_high_coupling_classes = tuple(
        sorted(
            set(current_snapshot.high_coupling_classes)
            - set(snapshot.high_coupling_classes)
        )
    )
    cycle_diff = _diff_cycles(
        baseline=snapshot.dependency_cycles,
        current=current_snapshot.dependency_cycles,
    )
    new_dead_code = tuple(
        sorted(set(current_snapshot.dead_code_items) - set(snapshot.dead_code_items))
    )

    if baseline_api_surface is None:
        added_api_symbols: tuple[str, ...] = ()
        api_breaking_changes: tuple[ApiBreakingChange, ...] = ()
    else:
        added_api_symbols, api_breaking_changes = compare_api_surfaces(
            baseline=baseline_api_surface,
            current=current_api_surface,
            strict_types=False,
        )

    return MetricsDiff(
        new_high_risk_functions=new_high_risk_functions,
        new_high_coupling_classes=new_high_coupling_classes,
        new_cycles=cycle_diff.new_cycles,
        new_import_cycles=cycle_diff.new_import_cycles,
        new_deferred_cycles=cycle_diff.new_deferred_cycles,
        cycle_kind_changes=cycle_diff.cycle_kind_changes,
        new_dead_code=new_dead_code,
        health_delta=_health_delta(
            baseline=snapshot.health_score,
            current=current_snapshot.health_score,
        ),
        typing_param_permille_delta=(
            current_snapshot.typing_param_permille - snapshot.typing_param_permille
        ),
        typing_return_permille_delta=(
            current_snapshot.typing_return_permille - snapshot.typing_return_permille
        ),
        docstring_permille_delta=(
            current_snapshot.docstring_permille - snapshot.docstring_permille
        ),
        new_api_symbols=added_api_symbols,
        new_api_breaking_changes=api_breaking_changes,
    )


__all__ = ["diff_clone_groups", "diff_metrics"]
