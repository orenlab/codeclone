# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from math import ceil

import pytest

from codeclone.analysis.cfg_model import CFG
from codeclone.contracts import (
    HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER,
    HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
)
from codeclone.metrics import complexity as complexity_mod
from codeclone.metrics import coupling as coupling_mod
from codeclone.metrics import health as health_mod
from codeclone.metrics.cohesion import cohesion_risk, compute_lcom4
from codeclone.metrics.complexity import (
    cyclomatic_complexity,
    nesting_depth,
    risk_level,
)
from codeclone.metrics.coupling import compute_cbo, coupling_risk
from codeclone.metrics.dead_code import find_suppressed_unused, find_unused
from codeclone.metrics.dependencies import (
    build_dep_graph,
    build_import_graph,
    depth_profile,
    find_cycles,
    longest_chains,
    max_depth,
)
from codeclone.metrics.health import HealthInputs, compute_health
from codeclone.models import DeadCandidate, DeadItem, ModuleDep
from codeclone.paths import is_test_filepath


def _parse_named_node(
    source: str,
    name: str,
) -> ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(source)
    for node in module.body:
        if (
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"top-level node {name!r} not found")


def test_cyclomatic_complexity_floor_and_nontrivial_graph() -> None:
    trivial_cfg = CFG("pkg.mod:f")
    assert cyclomatic_complexity(trivial_cfg) == 1

    cfg = CFG("pkg.mod:g")
    mid = cfg.create_block()
    cfg.entry.add_successor(mid)
    cfg.entry.add_successor(cfg.exit)
    mid.add_successor(cfg.exit)
    assert cyclomatic_complexity(cfg) == 2


@pytest.mark.parametrize(
    ("source", "name", "expected_depth"),
    [
        pytest.param(
            """
def f(x):
    if x:
        for i in range(3):
            if i:
                pass
    class Inner:
        def method(self):
            pass
""".strip(),
            "f",
            3,
            id="control_flow_and_generic_body",
        ),
        pytest.param(
            """
async def worker(items, value):
    async for item in items:
        async with item:
            match value:
                case 1:
                    while False:
                        pass
""".strip(),
            "worker",
            4,
            id="async_and_match",
        ),
        pytest.param(
            """
def choose(flag):
    if flag:
        return 1
    else:
        return 2
""".strip(),
            "choose",
            1,
            id="if_else_counts_as_one_level",
        ),
    ],
)
def test_nesting_depth_examples(
    source: str,
    name: str,
    expected_depth: int,
) -> None:
    func = _parse_named_node(source, name)
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    assert nesting_depth(func) == expected_depth


def test_iter_nested_statement_lists_try_and_empty_match() -> None:
    module = ast.parse(
        """
def f() -> None:
    try:
        x = 1
    except Exception:
        x = 2
    else:
        x = 3
    finally:
        x = 4
""".strip()
    )
    function = module.body[0]
    assert isinstance(function, ast.FunctionDef)
    try_stmt = function.body[0]
    assert isinstance(try_stmt, ast.Try)
    nested_lists = list(complexity_mod._iter_nested_statement_lists(try_stmt))
    assert len(nested_lists) == 4

    match_stmt = ast.Match(subject=ast.Name(id="x"), cases=[])
    assert list(complexity_mod._iter_nested_statement_lists(match_stmt)) == []
    assert list(complexity_mod._iter_nested_statement_lists(ast.Pass())) == []

    bare_try = ast.Try(body=[ast.Pass()], handlers=[], orelse=[], finalbody=[])
    assert list(complexity_mod._iter_nested_statement_lists(bare_try)) == [
        bare_try.body
    ]


def test_risk_level_boundaries() -> None:
    assert risk_level(10) == "low"
    assert risk_level(11) == "medium"
    assert risk_level(21) == "high"


def test_annotation_name_variants() -> None:
    name_node = ast.Name(id="TypeA")
    assert coupling_mod._annotation_name(name_node) == "TypeA"

    attr_node = ast.Attribute(value=ast.Name(id="pkg"), attr="TypeB")
    assert coupling_mod._annotation_name(attr_node) == "TypeB"

    subscript_node = ast.Subscript(value=ast.Name(id="list"), slice=ast.Name(id="int"))
    assert coupling_mod._annotation_name(subscript_node) == "list"

    tuple_node = ast.Tuple(
        elts=[ast.Constant(value=1), ast.Name(id="TypeC")], ctx=ast.Load()
    )
    assert coupling_mod._annotation_name(tuple_node) == "TypeC"
    assert (
        coupling_mod._annotation_name(
            ast.Tuple(elts=[ast.Constant(value=1)], ctx=ast.Load())
        )
        is None
    )

    assert coupling_mod._annotation_name(ast.Constant(value=1)) is None


def test_compute_cbo_filters_builtins_and_self_references() -> None:
    class_node = _parse_named_node(
        """
from ext import External, Helper

class Local:
    pass

class Sample(External):
    field: list[Helper]

    def __init__(self, dep: Helper) -> None:
        self.dep = dep
        self.local = Local()
        dep.api()
        self.run()
        len([])
""".strip(),
        "Sample",
    )
    assert isinstance(class_node, ast.ClassDef)
    cbo, resolved = compute_cbo(
        class_node,
        module_import_names={"External", "Helper"},
        module_class_names={"Sample", "Local"},
    )
    assert cbo == 3
    assert resolved == ("External", "Helper", "Local")


def test_compute_cbo_handles_non_symbolic_variants() -> None:
    synthetic = ast.ClassDef(
        name="Sample",
        bases=[ast.Constant(value=1)],
        keywords=[],
        body=[ast.Pass()],
        decorator_list=[],
    )
    cbo, resolved = compute_cbo(
        synthetic,
        module_import_names=set(),
        module_class_names={"Sample"},
    )
    assert cbo == 0
    assert resolved == ()

    class_node = _parse_named_node(
        """
class DynamicCalls:
    def run(self, value: "str") -> None:
        (lambda fn: fn)(value)
""".strip(),
        "DynamicCalls",
    )
    assert isinstance(class_node, ast.ClassDef)
    cbo_dynamic, resolved_dynamic = compute_cbo(
        class_node,
        module_import_names={"External"},
        module_class_names={"DynamicCalls"},
    )
    assert cbo_dynamic == 0
    assert resolved_dynamic == ()


def test_coupling_risk_boundaries() -> None:
    assert coupling_risk(5) == "low"
    assert coupling_risk(10) == "medium"
    assert coupling_risk(11) == "high"


def test_compute_lcom4_for_empty_and_partially_connected_class() -> None:
    cases = (
        (
            """
class Empty:
    value = 1
""".strip(),
            "Empty",
            (1, 0, 0),
        ),
        (
            """
class Service:
    def first(self) -> None:
        self.counter = 1
        self.second()

    def second(self) -> int:
        return self.counter

    def third(self) -> int:
        return 1
""".strip(),
            "Service",
            (2, 3, 2),
        ),
        (
            """
class Recursive:
    def left(self) -> None:
        self.right()

    def right(self) -> None:
        self.left()
""".strip(),
            "Recursive",
            (1, 2, 2),
        ),
        (
            """
class Triangle:
    def a(self) -> None:
        self.shared = 1
        self.b()

    def b(self) -> None:
        self.shared = 2
        self.c()

    def c(self) -> None:
        self.shared = 3
        self.a()
""".strip(),
            "Triangle",
            (1, 3, 4),
        ),
    )
    for source, name, expected in cases:
        class_node = _parse_named_node(source, name)
        assert isinstance(class_node, ast.ClassDef)
        assert compute_lcom4(class_node) == expected


def test_compute_lcom4_ignores_unknown_self_calls() -> None:
    class_node = _parse_named_node(
        """
class UnknownCall:
    def first(self) -> None:
        self.external()

    def second(self) -> None:
        pass
""".strip(),
        "UnknownCall",
    )
    assert isinstance(class_node, ast.ClassDef)
    assert compute_lcom4(class_node) == (2, 2, 1)


def test_cohesion_risk_boundaries() -> None:
    assert cohesion_risk(1) == "low"
    assert cohesion_risk(3) == "medium"
    assert cohesion_risk(4) == "high"


def test_find_unused_filters_non_actionable_and_preserves_ordering() -> None:
    definitions = (
        DeadCandidate(
            qualname="pkg.mod:used",
            local_name="used",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=1,
            kind="function",
        ),
        DeadCandidate(
            qualname="pkg.mod:dead",
            local_name="dead",
            filepath="pkg/mod.py",
            start_line=3,
            end_line=4,
            kind="function",
        ),
        DeadCandidate(
            qualname="pkg.mod:MaybeUsed",
            local_name="unreferenced_name",
            filepath="pkg/mod.py",
            start_line=2,
            end_line=2,
            kind="class",
        ),
        DeadCandidate(
            qualname="pkg.tests:test_func",
            local_name="test_func",
            filepath="pkg/tests/test_mod.py",
            start_line=5,
            end_line=5,
            kind="function",
        ),
        DeadCandidate(
            qualname="pkg.mod:Visitor.visit_Name",
            local_name="visit_Name",
            filepath="pkg/mod.py",
            start_line=6,
            end_line=6,
            kind="method",
        ),
        DeadCandidate(
            qualname="pkg.mod:Model.__repr__",
            local_name="__repr__",
            filepath="pkg/mod.py",
            start_line=7,
            end_line=7,
            kind="method",
        ),
        DeadCandidate(
            qualname="pkg.mod:Hooks.setup_method",
            local_name="setup_method",
            filepath="pkg/mod.py",
            start_line=8,
            end_line=8,
            kind="method",
        ),
        DeadCandidate(
            qualname="pkg.mod:__getattr__",
            local_name="__getattr__",
            filepath="pkg/mod.py",
            start_line=9,
            end_line=9,
            kind="function",
        ),
        DeadCandidate(
            qualname="pkg.mod:__dir__",
            local_name="__dir__",
            filepath="pkg/mod.py",
            start_line=10,
            end_line=10,
            kind="function",
        ),
        DeadCandidate(
            qualname="pkg.mod:suppressed",
            local_name="suppressed",
            filepath="pkg/mod.py",
            start_line=11,
            end_line=12,
            kind="function",
            suppressed_rules=("dead-code",),
        ),
    )
    found = find_unused(
        definitions=definitions,
        referenced_names=frozenset({"used", "MaybeUsed"}),
    )
    assert found == (
        DeadItem(
            qualname="pkg.mod:MaybeUsed",
            filepath="pkg/mod.py",
            start_line=2,
            end_line=2,
            kind="class",
            confidence="medium",
        ),
        DeadItem(
            qualname="pkg.mod:dead",
            filepath="pkg/mod.py",
            start_line=3,
            end_line=4,
            kind="function",
            confidence="high",
        ),
    )


def test_dead_code_test_filepath_helpers() -> None:
    candidate = DeadCandidate(
        qualname="pkg.mod:fixture",
        local_name="fixture",
        filepath="pkg/tests/helpers.py",
        start_line=1,
        end_line=1,
        kind="function",
    )
    assert find_unused(definitions=(candidate,), referenced_names=frozenset()) == ()
    assert is_test_filepath("pkg/tests/test_mod.py") is True

    regular_method = DeadCandidate(
        qualname="pkg.mod:Service.method",
        local_name="method",
        filepath="pkg/mod.py",
        start_line=2,
        end_line=3,
        kind="method",
    )
    found = find_unused(definitions=(regular_method,), referenced_names=frozenset())
    assert found and found[0].qualname == "pkg.mod:Service.method"


def test_find_unused_respects_referenced_qualnames() -> None:
    candidate = DeadCandidate(
        qualname="pkg.mod:wrapped",
        local_name="wrapped",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=3,
        kind="function",
    )
    found = find_unused(
        definitions=(candidate,),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg.mod:wrapped"}),
    )
    assert found == ()


def test_find_unused_applies_inline_dead_code_suppression() -> None:
    candidate = DeadCandidate(
        qualname="pkg.mod:runtime_callback",
        local_name="runtime_callback",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=2,
        kind="function",
        suppressed_rules=("dead-code",),
    )
    found = find_unused(definitions=(candidate,), referenced_names=frozenset())
    assert found == ()


def test_find_suppressed_unused_returns_actionable_suppressed_candidates() -> None:
    candidate = DeadCandidate(
        qualname="pkg.mod:runtime_callback",
        local_name="runtime_callback",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=2,
        kind="function",
        suppressed_rules=("dead-code",),
    )
    found = find_suppressed_unused(
        definitions=(candidate,),
        referenced_names=frozenset(),
    )
    assert found == (
        DeadItem(
            qualname="pkg.mod:runtime_callback",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            confidence="high",
        ),
    )


def test_find_unused_keeps_non_pep562_module_dunders_actionable() -> None:
    candidate = DeadCandidate(
        qualname="pkg.mod:__custom__",
        local_name="__custom__",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=2,
        kind="function",
    )
    found = find_unused(definitions=(candidate,), referenced_names=frozenset())
    assert found == (
        DeadItem(
            qualname="pkg.mod:__custom__",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            confidence="high",
        ),
    )


def test_build_import_graph_cycle_depth_and_chain_helpers() -> None:
    deps = (
        ModuleDep(source="a", target="b", import_type="import", line=1),
        ModuleDep(source="b", target="a", import_type="from_import", line=2),
        ModuleDep(source="c", target="c", import_type="import", line=3),
        ModuleDep(source="d", target="e", import_type="import", line=4),
    )
    graph = build_import_graph(modules={"d", "f"}, deps=deps)
    assert set(graph) == {"a", "b", "c", "d", "e", "f"}
    assert graph["a"] == {"b"}
    assert graph["f"] == set()

    cycles = find_cycles(graph)
    assert cycles == (("a", "b"), ("c",))
    assert max_depth(graph) >= 2
    assert longest_chains(graph, limit=0) == ()
    assert longest_chains(graph, limit=2)


def test_build_dep_graph_deduplicates_edges() -> None:
    repeated = ModuleDep(source="pkg.a", target="pkg.b", import_type="import", line=1)
    external = ModuleDep(source="pkg.a", target="typing", import_type="import", line=2)
    dep_graph = build_dep_graph(modules={"pkg.a"}, deps=(repeated, repeated, external))
    assert dep_graph.modules == frozenset({"pkg.a", "pkg.b"})
    assert dep_graph.edges == (repeated,)
    assert dep_graph.avg_depth == 1.5
    assert dep_graph.p95_depth == 2


def test_clone_piecewise_score_breakpoints() -> None:
    pw = health_mod._clone_piecewise_score
    assert pw(0.0) == 100
    assert pw(-0.1) == 100
    # First segment: 0 → 0.05 maps 100 → 90
    assert pw(0.025) == 95
    assert pw(0.05) == 90
    # Second segment: 0.05 → 0.20 maps 90 → 50
    assert pw(0.10) == 77  # 90 + (0.05/0.15)*(-40) ≈ 76.7 → 77
    assert pw(0.20) == 50
    # Third segment: 0.20 → 0.50 maps 50 → 0
    assert pw(0.35) == 25
    assert pw(0.50) == 0
    # Beyond last breakpoint
    assert pw(1.0) == 0


def test_health_helpers_and_compute_health_boundaries() -> None:
    assert health_mod._safe_div(10, 0) == 0.0
    assert health_mod._grade(95) == "A"
    assert health_mod._grade(80) == "B"
    assert health_mod._grade(65) == "C"
    assert health_mod._grade(45) == "D"
    assert health_mod._grade(10) == "F"

    health = compute_health(
        HealthInputs(
            files_found=0,
            files_analyzed_or_cached=0,
            function_clone_groups=50,
            block_clone_groups=50,
            complexity_avg=50.0,
            complexity_max=200,
            high_risk_functions=20,
            coupling_avg=20.0,
            coupling_max=50,
            high_risk_classes=10,
            cohesion_avg=10.0,
            low_cohesion_classes=10,
            dependency_cycles=10,
            dependency_max_depth=20,
            dependency_avg_depth=6.0,
            dependency_p95_depth=12,
            dead_code_items=30,
        )
    )
    assert 0 <= health.total <= 100
    assert health.grade in {"A", "B", "C", "D", "F"}
    assert set(health.dimensions) == {
        "clones",
        "complexity",
        "coupling",
        "cohesion",
        "dead_code",
        "dependencies",
        "coverage",
    }


def test_depth_profile_uses_nearest_rank_p95() -> None:
    graph = {
        "a": {"b"},
        "b": {"c"},
        "c": set(),
        "d": {"e"},
        "e": set(),
        "f": set(),
    }
    avg_depth, p95_depth = depth_profile(graph)
    assert avg_depth == pytest.approx((3 + 2 + 1 + 2 + 1 + 1) / 6)
    assert p95_depth == 3


def test_health_dependency_tail_pressure_is_adaptive() -> None:
    def _health_inputs(
        *,
        dependency_max_depth: int,
        dependency_avg_depth: float,
        dependency_p95_depth: int,
    ) -> HealthInputs:
        return HealthInputs(
            files_found=10,
            files_analyzed_or_cached=10,
            function_clone_groups=0,
            block_clone_groups=0,
            complexity_avg=0.0,
            complexity_max=0,
            high_risk_functions=0,
            coupling_avg=0.0,
            coupling_max=0,
            high_risk_classes=0,
            cohesion_avg=1.0,
            low_cohesion_classes=0,
            dependency_cycles=0,
            dependency_max_depth=dependency_max_depth,
            dependency_avg_depth=dependency_avg_depth,
            dependency_p95_depth=dependency_p95_depth,
            dead_code_items=0,
        )

    expected_tail = max(
        ceil(3.0 * HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER),
        5 + HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
    )
    safe = compute_health(
        _health_inputs(
            dependency_max_depth=expected_tail,
            dependency_avg_depth=3.0,
            dependency_p95_depth=5,
        )
    )
    warn = compute_health(
        _health_inputs(
            dependency_max_depth=expected_tail + 1,
            dependency_avg_depth=3.0,
            dependency_p95_depth=5,
        )
    )

    assert safe.dimensions["dependencies"] == 100
    assert warn.dimensions["dependencies"] == 96
