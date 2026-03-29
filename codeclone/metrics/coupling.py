# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import builtins
from typing import Literal

from ..contracts import COUPLING_RISK_LOW_MAX, COUPLING_RISK_MEDIUM_MAX

_BUILTIN_NAMES = frozenset(dir(builtins))


def _annotation_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Tuple):
        for element in node.elts:
            candidate = _annotation_name(element)
            if candidate:
                return candidate
    return None


def compute_cbo(
    class_node: ast.ClassDef,
    *,
    module_import_names: set[str],
    module_class_names: set[str],
) -> tuple[int, tuple[str, ...]]:
    """
    Conservative deterministic CBO approximation.

    We count unique external symbols referenced by class bases, annotations,
    constructor calls and non-self attributes.
    """
    couplings: set[str] = set()

    def _add_annotation_coupling(node: ast.AST | None) -> None:
        if node is None:
            return
        candidate = _annotation_name(node)
        if candidate:
            couplings.add(candidate)

    for base in class_node.bases:
        _add_annotation_coupling(base)

    for node in ast.walk(class_node):
        if isinstance(node, ast.Name):
            couplings.add(node.id)
        elif isinstance(node, ast.Attribute):
            if not (
                isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}
            ):
                couplings.add(node.attr)
        elif isinstance(node, ast.Call):
            _add_annotation_coupling(node.func)
        elif isinstance(node, (ast.AnnAssign, ast.arg)):
            _add_annotation_coupling(node.annotation)

    filtered = {
        name
        for name in couplings
        if name
        and name not in _BUILTIN_NAMES
        and name not in {"self", "cls", class_node.name}
        and (
            name in module_import_names
            or (name in module_class_names and name != class_node.name)
        )
    }
    resolved = tuple(sorted(filtered))
    return len(resolved), resolved


def coupling_risk(cbo: int) -> Literal["low", "medium", "high"]:
    if cbo <= COUPLING_RISK_LOW_MAX:
        return "low"
    if cbo <= COUPLING_RISK_MEDIUM_MAX:
        return "medium"
    return "high"
