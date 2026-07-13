# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..contracts import COHESION_RISK_MEDIUM_MAX
from ..models import ClassWalkFacts
from ._risk import RiskLevel, threshold_risk


def _build_adjacency(
    method_names: tuple[str, ...],
    method_to_attrs: dict[str, set[str]],
    method_calls: dict[str, set[str]],
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {name: set() for name in method_names}
    for name in method_names:
        adjacency[name].update(method_calls[name])
        for callee in method_calls[name]:
            adjacency.setdefault(callee, set()).add(name)

    for i, left in enumerate(method_names):
        left_attrs = method_to_attrs[left]
        for right in method_names[i + 1 :]:
            if left_attrs & method_to_attrs[right]:
                adjacency[left].add(right)
                adjacency[right].add(left)
    return adjacency


def _count_connected_components(
    method_names: tuple[str, ...],
    adjacency: dict[str, set[str]],
) -> int:
    visited: set[str] = set()
    components = 0

    for method_name in method_names:
        if method_name not in visited:
            components += 1
            stack = [method_name]
            while stack:
                current = stack.pop()
                if current not in visited:
                    visited.add(current)
                    stack.extend(sorted(adjacency[current] - visited))
    return components


def _instance_var_count(method_to_attrs: dict[str, set[str]]) -> int:
    if not method_to_attrs:
        return 0
    return len(set().union(*method_to_attrs.values()))


def _resolve_lcom4(
    facts: ClassWalkFacts,
) -> tuple[int, int, int]:
    method_names = tuple(facts.method_to_attrs)
    if len(method_names) <= 1:
        return 1, facts.all_method_count, _instance_var_count(facts.method_to_attrs)

    adjacency = _build_adjacency(
        method_names,
        facts.method_to_attrs,
        facts.method_calls,
    )
    components = _count_connected_components(method_names, adjacency)
    return (
        components,
        facts.all_method_count,
        _instance_var_count(facts.method_to_attrs),
    )


def cohesion_risk(lcom4: int) -> RiskLevel:
    return threshold_risk(lcom4, low_max=1, medium_max=COHESION_RISK_MEDIUM_MAX)
