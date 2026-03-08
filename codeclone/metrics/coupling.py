# SPDX-License-Identifier: MIT
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

    for base in class_node.bases:
        candidate = _annotation_name(base)
        if candidate:
            couplings.add(candidate)

    for node in ast.walk(class_node):
        if isinstance(node, ast.Name):
            couplings.add(node.id)
            continue
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
                continue
            couplings.add(node.attr)
            continue
        if isinstance(node, ast.Call):
            candidate = _annotation_name(node.func)
            if candidate:
                couplings.add(candidate)
            continue
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            candidate = _annotation_name(node.annotation)
            if candidate:
                couplings.add(candidate)
            continue
        if isinstance(node, ast.arg) and node.annotation is not None:
            candidate = _annotation_name(node.annotation)
            if candidate:
                couplings.add(candidate)

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
