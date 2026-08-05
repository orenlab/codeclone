# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Ratified source-decision table for public cyclomatic complexity (Wave D).

Every fixture below pins one cell of the maintainer-ratified normative table.
The fixtures were authored from the declared table BEFORE the implementation
existed (red-first) and validate the table; they must never be edited to make
an implementation pass — a mismatch means the implementation missed a
construct, not that a cell moved.

The public metric is a deterministic source-level decision count over AST
constructs and is entirely independent of CFG normalization and reachability.
``cfg_cyclomatic_complexity`` (E-N+2P over the single complete Y9 CFG) remains
a separate diagnostic and is pinned as *distinct* here, never derived from.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from codeclone.metrics.source_decisions import (
    SourceDecisionCounter,
    source_decision_complexity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = REPO_ROOT / "codeclone"


def _function(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(dedent(source))
    node = module.body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


def _cc(source: str) -> int:
    return source_decision_complexity(_function(source))


# ---------------------------------------------------------------------------
# Atomic acceptance fixtures: one cell of the ratified table each.
# ---------------------------------------------------------------------------


def test_base_callable_is_one() -> None:
    assert _cc("def f():\n    return 1\n") == 1


def test_single_if_adds_one() -> None:
    assert _cc("def f(a):\n    if a:\n        return 1\n    return 0\n") == 2


def test_each_elif_adds_one() -> None:
    source = """
    def f(a):
        if a == 1:
            return 1
        elif a == 2:
            return 2
        elif a == 3:
            return 3
        return 0
    """
    assert _cc(source) == 4


def test_if_with_boolop_counts_both() -> None:
    # if +1, BoolOp(a, b) +1 → 3 with the base path.
    assert _cc("def f(a, b):\n    if a and b:\n        return 1\n    return 0\n") == 3


def test_boolop_counts_in_any_expression_position() -> None:
    # `return cached or load()` is a short-circuit decision: +1.
    assert _cc("def f(cached, load):\n    return cached or load()\n") == 2


def test_mixed_boolops_are_two_nodes() -> None:
    # `a or b and c` = Or(a, And(b, c)) — two BoolOp nodes → +2.
    assert _cc("def f(a, b, c):\n    return a or b and c\n") == 3


def test_single_boolop_counts_n_minus_one() -> None:
    # `a or b or c` is ONE BoolOp with three values → +2.
    assert _cc("def f(a, b, c):\n    return a or b or c\n") == 3


def test_ternary_ifexp_adds_one() -> None:
    assert _cc("def f(a):\n    return 1 if a else 0\n") == 2


def test_while_adds_one() -> None:
    assert _cc("def f(n):\n    while n:\n        n -= 1\n    return n\n") == 2


def test_while_true_still_counts() -> None:
    # Reachability never filters the source count: the authored check counts
    # even when the CFG suppresses the literal-guard exit edge.
    assert _cc("def f():\n    while True:\n        return 1\n") == 2


def test_for_adds_one() -> None:
    assert _cc("def f(xs):\n    for x in xs:\n        x()\n    return 0\n") == 2


def test_async_for_adds_one() -> None:
    source = """
    async def f(xs):
        async for x in xs:
            await x()
        return 0
    """
    assert _cc(source) == 2


def test_assert_adds_one() -> None:
    assert _cc("def f(x):\n    assert x\n    return x\n") == 2


def test_assert_with_boolop_counts_both() -> None:
    assert _cc("def f(a, b):\n    assert a and b\n    return a\n") == 3


def test_try_with_two_except_clauses() -> None:
    source = """
    def f(x):
        try:
            return 10 // x
        except ZeroDivisionError:
            return 0
        except TypeError:
            return -1
    """
    assert _cc(source) == 3


def test_try_finally_without_handlers_is_base() -> None:
    source = """
    def f(x):
        try:
            return x()
        finally:
            x.close()
    """
    assert _cc(source) == 1


def test_try_else_is_derived_route() -> None:
    source = """
    def f(x):
        try:
            y = x()
        except ValueError:
            return 0
        else:
            return y
    """
    assert _cc(source) == 2


@pytest.mark.skipif(sys.version_info < (3, 11), reason="except* needs 3.11+")
def test_each_except_star_clause_adds_one() -> None:
    source = """
    def f(x):
        try:
            return x()
        except* ValueError:
            return 0
        except* TypeError:
            return -1
    """
    assert _cc(source) == 3


def test_single_comprehension_generator() -> None:
    assert _cc("def f(xs):\n    return [x for x in xs]\n") == 2


def test_generator_with_two_filters() -> None:
    assert _cc("def f(xs):\n    return [x for x in xs if x if x > 1]\n") == 4


def test_each_comprehension_generator_counts() -> None:
    assert _cc("def f(xs, ys):\n    return [x + y for x in xs for y in ys]\n") == 3


def test_comprehension_filter_boolop_counts_extra() -> None:
    assert _cc("def f(xs, a, b):\n    return [x for x in xs if a or b]\n") == 4


def test_match_two_cases_and_default() -> None:
    source = """
    def f(x):
        match x:
            case 1:
                return 1
            case 2:
                return 2
            case _:
                return 0
    """
    assert _cc(source) == 3


def test_guarded_default_is_not_a_default() -> None:
    # `case _ if allowed:` is NOT an unconditional default: the case counts 1
    # and the guard counts 1 separately.
    source = """
    def f(x, allowed):
        match x:
            case 1:
                return 1
            case 2:
                return 2
            case _ if allowed:
                return 0
    """
    assert _cc(source) == 5


def test_only_case_guarded_wildcard() -> None:
    source = """
    def f(x, allowed):
        match x:
            case _ if allowed:
                return 0
    """
    assert _cc(source) == 3


def test_last_bare_capture_is_not_the_wildcard_default() -> None:
    # The ratified table exempts exactly the last unguarded wildcard `_`;
    # a bare capture pattern is a case like any other.
    source = """
    def f(x):
        match x:
            case 1:
                return 1
            case other:
                return other
    """
    assert _cc(source) == 3


def test_match_or_counts_alternatives_minus_one() -> None:
    source = """
    def f(x):
        match x:
            case 1 | 2:
                return 1
            case _:
                return 0
    """
    assert _cc(source) == 3


def test_match_or_three_alternatives() -> None:
    source = """
    def f(x):
        match x:
            case 1 | 2 | 3:
                return 1
            case _:
                return 0
    """
    assert _cc(source) == 4


def test_guard_boolop_counts_extra() -> None:
    source = """
    def f(x, a, b):
        match x:
            case 1 if a or b:
                return 1
            case _:
                return 0
    """
    assert _cc(source) == 4


def test_with_suppressor_adds_nothing() -> None:
    source = """
    def f(path):
        from contextlib import suppress

        with suppress(OSError):
            path.unlink()
        return 0
    """
    assert _cc(source) == 1


def test_exception_capable_call_adds_nothing() -> None:
    # Implicit exception edges are not authored decisions.
    assert _cc("def f(g):\n    g()\n    return 1\n") == 1


def test_loop_else_is_derived_route() -> None:
    source = """
    def f(xs):
        for x in xs:
            if x:
                break
        else:
            return -1
        return 0
    """
    assert _cc(source) == 3


def test_jumps_add_nothing() -> None:
    source = """
    def f(xs):
        for x in xs:
            if x < 0:
                continue
            if x > 9:
                break
        return 0
    """
    assert _cc(source) == 4


def test_walrus_yield_await_add_nothing() -> None:
    source = """
    async def f(g):
        if (n := await g()):
            return n
        return 0
    """
    assert _cc(source) == 2


# ---------------------------------------------------------------------------
# Scope boundaries: nested definitions and lambda.
# ---------------------------------------------------------------------------


def test_nested_def_body_does_not_count() -> None:
    source = """
    def outer(x):
        def inner(y):
            if y:
                return y
            return 0

        return inner(x)
    """
    assert _cc(source) == 1


def test_nested_class_body_does_not_count() -> None:
    source = """
    def outer(x):
        class C:
            if x:
                flag = True

        return C
    """
    assert _cc(source) == 1


def test_nested_def_decorator_evaluates_in_outer_flow() -> None:
    # The nested body is excluded, but the nested def's decorator expression
    # runs when the outer `def` statement runs — its BoolOp counts here.
    source = """
    def outer(deco, a, b):
        @deco(a or b)
        def inner(y):
            if y:
                return y
            return 0

        return inner
    """
    assert _cc(source) == 2


def test_lambda_decisions_count_toward_enclosing_unit() -> None:
    # Lambda is not a metric unit under the existing contract
    # (qualnames.FunctionNode is FunctionDef | AsyncFunctionDef), so it does
    # not count separately; its authored decisions belong to the unit whose
    # source authored them.
    source = """
    def f(xs, p):
        return sorted(xs, key=lambda v: v.a if p else v.b)
    """
    assert _cc(source) == 2


def test_outer_unit_own_decorators_do_not_count() -> None:
    # A unit's own decorators run in the ENCLOSING scope's flow when the
    # `def` statement executes, not on the unit's own paths.
    source = """
    @deco(a or b)
    def f(x):
        return x
    """
    assert _cc(source) == 1


# ---------------------------------------------------------------------------
# Metamorphic pins: the public metric is CFG-independent.
# ---------------------------------------------------------------------------

_PLAIN = """
def f(x):
    if x:
        return 1
    return 0
"""

_WITH_FINALLY = """
def f(x):
    try:
        if x:
            return 1
        return 0
    finally:
        pass
"""

_WITH_UNREACHABLE_TAIL = """
def f(x):
    if x:
        return 1
    return 0
    x += 1
"""


def test_finally_routing_leaves_public_metric_unchanged() -> None:
    assert _cc(_PLAIN) == _cc(_WITH_FINALLY) == 2


def test_cfg_shape_change_leaves_public_metric_unchanged() -> None:
    # The post-terminator tail becomes a real unreachable CFG block (its own
    # weakly connected component) and moves E-N+2P; the source decision count
    # must not move.
    assert _cc(_PLAIN) == _cc(_WITH_UNREACHABLE_TAIL) == 2


def test_public_metric_diverges_from_cfg_diagnostic() -> None:
    # The two metrics are genuinely distinct on exception-routing shapes:
    # E-N+2P over the complete Y9 CFG counts dispatch/finally routing that the
    # source-decision table declares as 0.
    from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
    from codeclone.analysis.normalizer import NormalizationConfig
    from tests._ast_metrics_helpers import bindings_for_function_node

    func = _function(_WITH_FINALLY)
    _graph, _fingerprint, cfg_metric = _cfg_fingerprint_and_complexity(
        func,
        NormalizationConfig(),
        "m:f",
        bindings_for_function_node(func),
    )
    assert source_decision_complexity(func) == 2
    assert cfg_metric != 2


def test_assert_is_source_defined() -> None:
    # The metric is defined over the source AST as parsed by the analyzer
    # (ast.parse with default, non-optimizing flags), so `python -O` runtime
    # semantics can never move it: the authored `assert` stays in the source.
    source = "def f(x):\n    assert x\n    return x\n"
    assert _cc(source) == 2
    # Same source, byte-identical parse — the counter is deterministic.
    assert _cc(source) == _cc(source)


def test_counter_is_read_only() -> None:
    source = "def f(a, b):\n    if a and b:\n        return 1\n    return 0\n"
    func = _function(source)
    before = ast.dump(func)
    counter = SourceDecisionCounter()
    for statement in func.body:
        counter.visit(statement)
    assert counter.decisions == 2
    assert ast.dump(func) == before


# ---------------------------------------------------------------------------
# Single-owner guard: mechanical inventory against a second complexity owner.
# ---------------------------------------------------------------------------

_OWNER = Path("codeclone/metrics/source_decisions.py")
_CFG_METRIC = Path("codeclone/metrics/complexity.py")
_FINGERPRINT = Path("codeclone/analysis/fingerprint.py")
_CANONICAL_EMITTER = Path("codeclone/analysis/wire.py")
_CFG_BUILDER = Path("codeclone/analysis/cfg.py")

#: Node-type names that characterize a source-decision table. A module that
#: speaks this vocabulary is either the single owner, the canonical wire
#: emitter (serializes every node kind), or the CFG builder (branches on
#: BoolOp for short-circuit blocks) — anything else is a second owner.
_DECISION_MARKERS = ("IfExp", "MatchOr", "BoolOp", "ExceptHandler")


def _production_files() -> list[Path]:
    return sorted(PRODUCTION_ROOT.rglob("*.py"))


def test_single_owner_no_second_cyclomatic_definition() -> None:
    """Any def/class whose name says 'cyclomatic' or 'source_decision' must
    live in the declared owner modules and nowhere else."""

    allowed = {
        (_CFG_METRIC, "cfg_cyclomatic_complexity"),
        (_OWNER, "SourceDecisionCounter"),
        (_OWNER, "source_decision_complexity"),
    }
    found: set[tuple[Path, str]] = set()
    for path in _production_files():
        tree = ast.parse(path.read_text("utf-8"))
        relative = path.relative_to(REPO_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if "cyclomatic" in lowered or "sourcedecision" in lowered.replace(
                    "_", ""
                ):
                    found.add((relative, node.name))
    assert found == allowed


def test_single_owner_decision_vocabulary_inventory() -> None:
    """A new module that references the decision node-type vocabulary is a
    second decision counter until this inventory is consciously amended."""

    allowed = {_OWNER, _CANONICAL_EMITTER, _CFG_BUILDER}
    speakers: set[Path] = set()
    for path in _production_files():
        text = path.read_text("utf-8")
        markers = sum(1 for marker in _DECISION_MARKERS if marker in text)
        if markers >= 2:
            speakers.add(path.relative_to(REPO_ROOT))
    assert speakers == allowed


def test_public_metric_binds_to_the_single_owner() -> None:
    """units.py must assign Unit.cyclomatic_complexity from
    source_decision_complexity(...) and Unit.cfg_cyclomatic_complexity from
    the _cfg_fingerprint_and_complexity tuple — never the other way around."""

    tree = ast.parse((REPO_ROOT / "codeclone/analysis/units.py").read_text("utf-8"))
    bindings: dict[str, ast.expr] = {}
    # Provenance of every simple local: name → producing call's name, for
    # both plain assignments and tuple-unpacked results.
    producers: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            callee_name = callee.id if isinstance(callee, ast.Name) else None
            if callee_name is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    producers[target.id] = callee_name
                elif isinstance(target, ast.Tuple):
                    for element in target.elts:
                        if isinstance(element, ast.Name):
                            producers[element.id] = callee_name
        if isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id == "Unit":
                for keyword in node.keywords:
                    if keyword.arg in {
                        "cyclomatic_complexity",
                        "cfg_cyclomatic_complexity",
                    }:
                        assert keyword.arg is not None
                        bindings[keyword.arg] = keyword.value
    assert set(bindings) == {"cyclomatic_complexity", "cfg_cyclomatic_complexity"}
    public = bindings["cyclomatic_complexity"]
    assert isinstance(public, ast.Name)
    assert producers[public.id] == "source_decision_complexity"
    diagnostic = bindings["cfg_cyclomatic_complexity"]
    assert isinstance(diagnostic, ast.Name)
    assert producers[diagnostic.id] == "_cfg_fingerprint_and_complexity"


def test_owner_never_imports_cfg_or_cache() -> None:
    """The public metric must not be built through the CFG or fingerprint
    wire even indirectly: the owner module imports neither codeclone.analysis
    nor codeclone.cache."""

    tree = ast.parse((REPO_ROOT / _OWNER).read_text("utf-8"))
    forbidden = ("analysis", "cache")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not any(part in name.split(".") for part in forbidden), name
