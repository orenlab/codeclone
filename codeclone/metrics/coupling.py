# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import builtins

from ..contracts import COUPLING_RISK_LOW_MAX, COUPLING_RISK_MEDIUM_MAX
from ._risk import RiskLevel, threshold_risk

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


def _resolve_cbo(
    couplings: frozenset[str],
    *,
    class_name: str,
    module_import_names: set[str],
    module_class_names: set[str],
) -> tuple[int, tuple[str, ...]]:
    filtered = {
        name
        for name in couplings
        if name
        and name not in _BUILTIN_NAMES
        and name not in {"self", "cls", class_name}
        and (
            name in module_import_names
            or (name in module_class_names and name != class_name)
        )
    }
    resolved = tuple(sorted(filtered))
    return len(resolved), resolved


def coupling_risk(cbo: int) -> RiskLevel:
    return threshold_risk(
        cbo,
        low_max=COUPLING_RISK_LOW_MAX,
        medium_max=COUPLING_RISK_MEDIUM_MAX,
    )
