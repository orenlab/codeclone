# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

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


def compute_lcom4(class_node: ast.ClassDef) -> tuple[int, int, int]:
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = [
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    method_names = tuple(method.name for method in methods)
    if not methods:
        return 1, 0, 0

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

    instance_vars = set().union(*method_to_attrs.values()) if method_to_attrs else set()
    return components, len(method_names), len(instance_vars)


def cohesion_risk(lcom4: int) -> RiskLevel:
    return threshold_risk(lcom4, low_max=1, medium_max=COHESION_RISK_MEDIUM_MAX)
