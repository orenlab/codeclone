from __future__ import annotations

import ast

from codeclone.cfg_model import CFG
from codeclone.metrics import (
    HealthInputs,
    build_dep_graph,
    build_import_graph,
    cohesion_risk,
    compute_cbo,
    compute_health,
    compute_lcom4,
    coupling_risk,
    cyclomatic_complexity,
    find_cycles,
    find_unused,
    longest_chains,
    max_depth,
    nesting_depth,
    risk_level,
)
from codeclone.metrics import complexity as complexity_mod
from codeclone.metrics import coupling as coupling_mod
from codeclone.metrics import health as health_mod
from codeclone.models import DeadCandidate, DeadItem, ModuleDep
from codeclone.paths import is_test_filepath


def _parse_class(source: str, name: str) -> ast.ClassDef:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name!r} not found")


def _parse_function(source: str, name: str) -> ast.FunctionDef:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _parse_async_function(source: str, name: str) -> ast.AsyncFunctionDef:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"async function {name!r} not found")


def test_cyclomatic_complexity_floor_and_nontrivial_graph() -> None:
    trivial_cfg = CFG("pkg.mod:f")
    assert cyclomatic_complexity(trivial_cfg) == 1

    cfg = CFG("pkg.mod:g")
    mid = cfg.create_block()
    cfg.entry.add_successor(mid)
    cfg.entry.add_successor(cfg.exit)
    mid.add_successor(cfg.exit)
    assert cyclomatic_complexity(cfg) == 2


def test_nesting_depth_covers_control_flow_and_generic_body_nodes() -> None:
    func = _parse_function(
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
    )
    assert nesting_depth(func) == 3


def test_nesting_depth_handles_async_and_match_nodes() -> None:
    func = _parse_async_function(
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
    )
    assert nesting_depth(func) == 4


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
    class_node = _parse_class(
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

    class_node = _parse_class(
        """
class DynamicCalls:
    def run(self, value: "str") -> None:
        (lambda fn: fn)(value)
""".strip(),
        "DynamicCalls",
    )
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
    empty_class = _parse_class(
        """
class Empty:
    value = 1
""".strip(),
        "Empty",
    )
    assert compute_lcom4(empty_class) == (1, 0, 0)

    class_node = _parse_class(
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
    )
    assert compute_lcom4(class_node) == (2, 3, 2)

    recursive = _parse_class(
        """
class Recursive:
    def left(self) -> None:
        self.right()

    def right(self) -> None:
        self.left()
""".strip(),
        "Recursive",
    )
    assert compute_lcom4(recursive) == (1, 2, 2)

    triangle = _parse_class(
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
    )
    assert compute_lcom4(triangle) == (1, 3, 4)


def test_compute_lcom4_ignores_unknown_self_calls() -> None:
    class_node = _parse_class(
        """
class UnknownCall:
    def first(self) -> None:
        self.external()

    def second(self) -> None:
        pass
""".strip(),
        "UnknownCall",
    )
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
    dep_graph = build_dep_graph(modules={"pkg.a"}, deps=(repeated, repeated))
    assert dep_graph.modules == frozenset({"pkg.a", "pkg.b"})
    assert dep_graph.edges == (repeated,)


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
