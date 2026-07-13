# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

from ..models import ClassWalkFacts
from .coupling import _annotation_name


def _class_methods(
    class_node: ast.ClassDef,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _add_coupling(couplings: set[str], node: ast.AST) -> None:
    candidate: str | None = None
    if isinstance(node, ast.Name):
        candidate = node.id
    elif isinstance(node, ast.Attribute):
        if not (isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}):
            candidate = node.attr
    elif isinstance(node, ast.Call):
        candidate = _annotation_name(node.func)
    elif isinstance(node, ast.AnnAssign | ast.arg):
        annotation = node.annotation
        if annotation is not None:
            candidate = _annotation_name(annotation)
    if candidate:
        couplings.add(candidate)


def _collect_method_node(
    *,
    node: ast.AST,
    method_name: str,
    method_to_attrs: dict[str, set[str]],
    method_calls: dict[str, set[str]],
) -> None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        method_to_attrs[method_name].add(node.attr)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr in method_calls
    ):
        method_calls[method_name].add(node.func.attr)


def collect_class_walk_facts(
    class_node: ast.ClassDef,
    *,
    analyzed_method_names: frozenset[str],
) -> ClassWalkFacts:
    """Collect coupling and cohesion inputs in one partitioned class walk."""
    couplings: set[str] = set()
    methods = _class_methods(class_node)
    method_to_attrs: dict[str, set[str]] = {
        method.name: set() for method in methods if method.name in analyzed_method_names
    }
    method_calls: dict[str, set[str]] = {name: set() for name in method_to_attrs}

    for base in class_node.bases:
        candidate = _annotation_name(base)
        if candidate:
            couplings.add(candidate)

    for child in ast.iter_child_nodes(class_node):
        method = (
            child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else None
        )
        for node in ast.walk(child):
            _add_coupling(couplings, node)
            if method is not None and method.name in method_to_attrs:
                _collect_method_node(
                    node=node,
                    method_name=method.name,
                    method_to_attrs=method_to_attrs,
                    method_calls=method_calls,
                )

    return ClassWalkFacts(
        couplings=frozenset(couplings),
        method_to_attrs=method_to_attrs,
        method_calls=method_calls,
        all_method_count=len(methods),
    )


__all__ = ["collect_class_walk_facts"]
