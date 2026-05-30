# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from collections.abc import Sequence

from ..contracts import COHESION_RISK_MEDIUM_MAX
from ._risk import RiskLevel, threshold_risk


def _self_attribute_name(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _class_methods(
    class_node: ast.ClassDef,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _collect_method_cohesion_facts(
    methods: Sequence[ast.FunctionDef | ast.AsyncFunctionDef],
    method_names: tuple[str, ...],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    method_to_attrs: dict[str, set[str]] = {name: set() for name in method_names}
    method_calls: dict[str, set[str]] = {name: set() for name in method_names}
    for method in methods:
        for node in ast.walk(method):
            attr_name = _self_attribute_name(node)
            if attr_name is not None:
                method_to_attrs[method.name].add(attr_name)
                continue
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                callee = node.func.attr
                if callee in method_calls:
                    method_calls[method.name].add(callee)
    return method_to_attrs, method_calls


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


def compute_lcom4(
    class_node: ast.ClassDef,
    *,
    ignored_methods: frozenset[str] = frozenset(),
) -> tuple[int, int, int]:
    """Compute LCOM4 cohesion over behavior-carrying methods.

    ``ignored_methods`` are excluded from the cohesion graph (Protocol stub
    methods and Pydantic validator/serializer hooks). They never carry
    instance-level behavioral cohesion, so counting them inflates the
    component count. The reported ``method_count`` still reflects all methods
    so the class size stays honest; only the cohesion graph and component
    count use the analyzed subset. When one or zero analyzed methods remain,
    cohesion is not measurable and LCOM4 collapses to ``1`` (no penalty).
    """
    all_methods = _class_methods(class_node)
    all_method_count = len(all_methods)
    analyzed_methods = [
        method for method in all_methods if method.name not in ignored_methods
    ]
    method_names = tuple(method.name for method in analyzed_methods)

    method_to_attrs, method_calls = _collect_method_cohesion_facts(
        analyzed_methods,
        method_names,
    )
    if len(analyzed_methods) <= 1:
        return 1, all_method_count, _instance_var_count(method_to_attrs)

    adjacency = _build_adjacency(method_names, method_to_attrs, method_calls)
    components = _count_connected_components(method_names, adjacency)
    return components, all_method_count, _instance_var_count(method_to_attrs)


def cohesion_risk(lcom4: int) -> RiskLevel:
    return threshold_risk(lcom4, low_max=1, medium_max=COHESION_RISK_MEDIUM_MAX)
