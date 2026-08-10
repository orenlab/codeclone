# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Public cyclomatic complexity: a deterministic source-level decision count.

Single owner of the public ``cyclomatic_complexity`` metric (maintainer
ratification, Wave D). The metric is a count of authored decisions over AST
constructs — the ratified normative table below, encoded declaratively — and
is entirely independent of CFG normalization and reachability. It must never
be built through the CFG or the fingerprint wire, even indirectly; the guard
in ``tests/test_source_decisions.py`` enforces both the single ownership and
this module's import purity.

``cfg_cyclomatic_complexity`` (E-N+2P over the single complete Y9 CFG,
``codeclone.metrics.complexity.cfg_cyclomatic_complexity``) remains a separate
diagnostic; nothing here reads it and nothing there reads this.

Ratified table:

===========================================  ============================
Construct                                    Contribution
===========================================  ============================
base callable                                1
``if`` / each ``elif``                       +1
``IfExp`` (ternary)                          +1
``while``                                    +1
``for`` / ``async for``                      +1
each comprehension generator                 +1
each ``if`` in a comprehension               +1
``BoolOp``                                   +(n-1), any expression position
each ``except`` / ``except*`` clause         +1
``try``-``else`` / ``finally``               0
each ``match`` case                          +1 (see wildcard rule)
last unguarded ``case _``                    0
guard on any case                            +1
``MatchOr`` (``case A | B``)                 +(n-1)
``assert``                                   +1 (source-defined; ``-O``
                                             never moves the metric)
``with`` / ``async with`` / suppressors      0
implicit exception edges                     0
loop-``else``                                0
``return``/``raise``/``break``/``continue``  0
``yield``/``await``/walrus                   0
===========================================  ============================

Scope boundaries: nested ``def``/``class`` bodies do not count toward the
outer unit — their decorators, argument defaults and annotations do, because
those expressions evaluate when the enclosing ``def``/``class`` statement
runs. Lambda is not a metric unit under the existing contract
(``codeclone.qualnames.FunctionNode`` is ``FunctionDef | AsyncFunctionDef``,
checked), so it never counts separately; and being a deferred-execution
nested scope like a nested ``def``, its body runs when the lambda is called,
not on the enclosing unit's own paths, so its body decisions count nowhere.
A lambda's *defaults* do count toward the enclosing unit, because they
evaluate when the lambda expression is evaluated — on the enclosing path.
A unit's own decorators and parameter defaults evaluate in the *enclosing*
scope's flow and never count toward the unit.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Final

__all__ = ["SourceDecisionCounter", "source_decision_complexity"]


def _one(_node: ast.AST) -> int:
    return 1


def _boolop(node: ast.AST) -> int:
    # Each short-circuit boundary is one authored decision. Nested BoolOps
    # (`a or b and c`) are separate nodes and contribute separately.
    assert isinstance(node, ast.BoolOp)
    return len(node.values) - 1


def _comprehension(node: ast.AST) -> int:
    # Each `for` generator is its own loop; each `if` is a separate filter.
    assert isinstance(node, ast.comprehension)
    return 1 + len(node.ifs)


def _match_or(node: ast.AST) -> int:
    # Authored pattern alternatives: `case A | B | C` is two boundaries.
    assert isinstance(node, ast.MatchOr)
    return len(node.patterns) - 1


#: The ratified table, node type → contribution. Constructs absent from this
#: mapping (and from the ``visit_Match`` case rule) contribute 0 by contract:
#: ``with``/``async with``, suppression context managers, ``try``-``else``,
#: ``finally``, loop-``else``, jumps, ``yield``/``await``/walrus, and implicit
#: exception edges are routing or protocol mechanics, not authored decisions.
#: ``ast.ExceptHandler`` covers both ``except`` and ``except*`` clauses.
_CONTRIBUTIONS: Final[dict[type[ast.AST], Callable[[ast.AST], int]]] = {
    ast.If: _one,  # each `if` and each `elif` (an `elif` is a nested If)
    ast.IfExp: _one,
    ast.While: _one,
    ast.For: _one,
    ast.AsyncFor: _one,
    ast.Assert: _one,  # authored binary decision; source-defined, `-O`-proof
    ast.ExceptHandler: _one,
    ast.BoolOp: _boolop,
    ast.comprehension: _comprehension,
    ast.MatchOr: _match_or,
}


def _is_unguarded_wildcard(case: ast.match_case) -> bool:
    """Exactly ``case _:`` with no guard — the ratified default exemption.

    A bare capture (``case other:``) is irrefutable too, but the ratified
    table exempts only the wildcard; ``case _ if allowed:`` is NOT an
    unconditional default.
    """

    pattern = case.pattern
    return (
        case.guard is None
        and isinstance(pattern, ast.MatchAs)
        and pattern.pattern is None
        and pattern.name is None
    )


class SourceDecisionCounter(ast.NodeVisitor):
    """Read-only deterministic visitor accumulating authored decisions.

    Visit a unit's *body statements* (never the unit node itself — the unit's
    own decorators and defaults belong to the enclosing scope) and read
    ``decisions``. ``source_decision_complexity`` is the public entry point.
    """

    __slots__ = ("decisions",)

    def __init__(self) -> None:
        self.decisions = 0

    def generic_visit(self, node: ast.AST) -> None:
        contribution = _CONTRIBUTIONS.get(type(node))
        if contribution is not None:
            self.decisions += contribution(node)
        super().generic_visit(node)

    # -- match: the only position-dependent rule in the table ---------------

    def visit_Match(self, node: ast.Match) -> None:
        last_index = len(node.cases) - 1
        for index, case in enumerate(node.cases):
            if not (index == last_index and _is_unguarded_wildcard(case)):
                self.decisions += 1
            if case.guard is not None:
                self.decisions += 1
        self.generic_visit(node)

    # -- nested scopes: bodies are excluded, def-time expressions count -----

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # A lambda is a deferred-execution nested scope, like a nested def: its
        # body runs when the lambda is CALLED, not on the enclosing unit's own
        # paths, and lambda is not a metric unit under the existing contract
        # (qualnames.FunctionNode excludes it), so its body decisions count
        # nowhere. Its defaults, however, evaluate when the lambda expression
        # is evaluated — on the enclosing unit's path — so they count, exactly
        # like a nested def's defaults.
        self.visit(node.args)

    def _visit_nested_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)


def source_decision_complexity(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> int:
    """Public cyclomatic complexity of one metric unit: 1 + authored decisions.

    The base callable is one independent path; every ratified table row adds
    its contribution. Pure function of the parsed source AST — no CFG, no
    normalization, no reachability, no wire.
    """

    counter = SourceDecisionCounter()
    for statement in node.body:
        counter.visit(statement)
    return 1 + counter.decisions
