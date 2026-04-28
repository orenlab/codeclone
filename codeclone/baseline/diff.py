# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Set

from ..metrics.api_surface import compare_api_surfaces
from ..models import (
    ApiBreakingChange,
    ApiSurfaceSnapshot,
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
    new_cycles = tuple(
        sorted(
            set(current_snapshot.dependency_cycles) - set(snapshot.dependency_cycles)
        )
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
        new_cycles=new_cycles,
        new_dead_code=new_dead_code,
        health_delta=current_snapshot.health_score - snapshot.health_score,
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
