# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    ignore_docstrings: bool = True
    ignore_type_annotations: bool = True
    normalize_constants: bool = True
    normalize_names: bool = True


def _is_proven_commutative_operand(node: ast.AST, op: ast.operator) -> bool:
    if isinstance(node, ast.Constant):
        return _is_proven_commutative_constant(node.value, op)
    if isinstance(node, ast.BinOp) and type(node.op) is type(op):
        return _is_proven_commutative_operand(
            node.left, op
        ) and _is_proven_commutative_operand(node.right, op)
    return False


def _is_proven_commutative_constant(value: object, op: ast.operator) -> bool:
    if isinstance(op, (ast.BitOr, ast.BitAnd, ast.BitXor)):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(op, (ast.Add, ast.Mult)):
        return isinstance(value, (int, float, complex)) and not isinstance(value, bool)
    return False
