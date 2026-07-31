# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ..contracts import COMPLEXITY_RISK_LOW_MAX, COMPLEXITY_RISK_MEDIUM_MAX
from ._risk import RiskLevel, threshold_risk

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..analysis.cfg_model import CFG

ControlNode = (
    ast.If
    | ast.For
    | ast.While
    | ast.Try
    | ast.With
    | ast.Match
    | ast.AsyncFor
    | ast.AsyncWith
)


def _weakly_connected_components(cfg: CFG) -> int:
    """Count the graph's weakly connected components — the ``P`` of McCabe.

    Unreachable code forms its own component now that the norm CFG keeps it,
    and the generalized formula is what stops such a function being scored as
    though that code were not there.
    """

    parent = {block.id: block.id for block in cfg.blocks}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for block in cfg.blocks:
        for successor in block.successors:
            left, right = find(block.id), find(successor.id)
            if left != right:
                parent[left] = right
    return len({find(block.id) for block in cfg.blocks})


def cyclomatic_complexity(cfg: CFG) -> int:
    """Full McCabe over the whole graph: ``V(G) = E - N + 2P``.

    Every edge counts. Exception dispatch, ``finally`` routing and
    context-manager suppression are real control flow, so dropping them — or
    filtering by an edge's kind to reproduce the numbers this metric gave
    before those edges existed — would reintroduce the second truth the norm
    CFG removed (39Y Y9, maintainer ruling A). Values move corpus-wide as a
    result, and the new ones are the true ones.
    """

    node_count = len(cfg.blocks)
    edge_count = sum(len(block.successors) for block in cfg.blocks)
    components = _weakly_connected_components(cfg)
    return max(1, edge_count - node_count + 2 * components)


def _iter_nested_statement_lists(node: ast.AST) -> Iterable[list[ast.stmt]]:
    if isinstance(node, (ast.If, ast.For, ast.While, ast.AsyncFor)):
        yield node.body
        if node.orelse:
            yield node.orelse
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        yield node.body
    elif isinstance(node, ast.Try):
        yield node.body
        if node.orelse:
            yield node.orelse
        if node.finalbody:
            yield node.finalbody
        for handler in node.handlers:
            yield handler.body
    elif isinstance(node, ast.Match):
        for case in node.cases:
            yield case.body


def nesting_depth(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Compute maximum nesting depth for control-flow statements."""

    def _visit_statements(statements: list[ast.stmt], depth: int) -> int:
        best = depth
        for statement in statements:
            if isinstance(
                statement,
                (
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.Try,
                    ast.With,
                    ast.Match,
                    ast.AsyncFor,
                    ast.AsyncWith,
                ),
            ):
                next_depth = depth + 1
                best = max(best, next_depth)
                for nested in _iter_nested_statement_lists(statement):
                    best = max(best, _visit_statements(nested, next_depth))
            else:
                nested_body = getattr(statement, "body", None)
                if isinstance(nested_body, list):
                    best = max(best, _visit_statements(nested_body, depth))
        return best

    return _visit_statements(list(func_node.body), 0)


def risk_level(cc: int) -> RiskLevel:
    return threshold_risk(
        cc,
        low_max=COMPLEXITY_RISK_LOW_MAX,
        medium_max=COMPLEXITY_RISK_MEDIUM_MAX,
    )
