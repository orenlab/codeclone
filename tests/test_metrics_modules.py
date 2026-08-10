# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import replace
from math import ceil
from pathlib import Path
from typing import Literal

import pytest

from codeclone.analysis.cfg_model import CFG
from codeclone.contracts import (
    COUPLING_RISK_LOW_MAX,
    COUPLING_RISK_MEDIUM_MAX,
    HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER,
    HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
    SOURCE_KIND_POLICY_VERSION,
)
from codeclone.metrics import complexity as complexity_mod
from codeclone.metrics import coupling as coupling_mod
from codeclone.metrics import health as health_mod
from codeclone.metrics.class_facts import collect_class_walk_facts
from codeclone.metrics.cohesion import _resolve_lcom4, cohesion_risk
from codeclone.metrics.complexity import (
    cfg_cyclomatic_complexity,
    nesting_depth,
    risk_level,
)
from codeclone.metrics.coupling import (
    _resolve_cbo,
    coupling_risk,
    resolve_project_class_coupling,
)
from codeclone.metrics.dead_code import (
    classify_liveness,
    find_suppressed_unused,
    find_unused,
)
from codeclone.metrics.dependencies import (
    _is_internal_target,
    _registry_modules,
    build_dep_graph,
    build_import_graph,
    depth_profile,
    find_cycles,
    longest_chains,
    max_depth,
    select_dependency_graph_nodes,
)
from codeclone.metrics.health import HealthInputs, compute_health
from codeclone.models import (
    ClassMetrics,
    ClassWalkFacts,
    DeadCandidate,
    DeadItem,
    ModuleDep,
)
from codeclone.paths import classify_source_kind, is_test_filepath
from tests._ast_metrics_helpers import (
    build_test_module_registry,
    module_registry_context,
)


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


def _class_walk_facts(
    class_node: ast.ClassDef,
    *,
    ignored_methods: frozenset[str] = frozenset(),
    imported_symbol_targets: Mapping[str, str] | None = None,
    imported_module_targets: Mapping[str, str] | None = None,
) -> ClassWalkFacts:
    method_names = frozenset(
        node.name
        for node in class_node.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name not in ignored_methods
    )
    return collect_class_walk_facts(
        class_node,
        analyzed_method_names=method_names,
        imported_symbol_targets=imported_symbol_targets or {},
        imported_module_targets=imported_module_targets or {},
    )


def test_dependency_registry_membership_and_target_guards() -> None:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=("pkg.sub",),
    )[1]
    assert _registry_modules(registry) == frozenset({"pkg.mod", "pkg.sub"})
    assert _is_internal_target("", registry=registry) is False
    assert _is_internal_target("pkg.sub", registry=registry) is True
    assert _is_internal_target("ext.b", registry=registry) is False


def test_cfg_cyclomatic_complexity_floor_and_nontrivial_graph() -> None:
    # 39Y Y9 ruling A: V(G) = E - N + 2P, so P is counted rather than assumed
    # to be 1. A bare CFG is two blocks with no edge between them — genuinely
    # two components — and the formula says 2. Every graph a builder actually
    # produces links its entry to its exit, which is the single-component case
    # below; this one is only reachable by constructing a CFG by hand.
    disconnected = CFG("pkg.mod:f")
    assert cfg_cyclomatic_complexity(disconnected) == 2

    connected = CFG("pkg.mod:trivial")
    connected.entry.add_successor(connected.exit)
    assert cfg_cyclomatic_complexity(connected) == 1

    cfg = CFG("pkg.mod:g")
    mid = cfg.create_block()
    cfg.entry.add_successor(mid)
    cfg.entry.add_successor(cfg.exit)
    mid.add_successor(cfg.exit)
    assert cfg_cyclomatic_complexity(cfg) == 2


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


def test_resolve_cbo_filters_builtins_and_self_references() -> None:
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
    facts = _class_walk_facts(class_node)
    cbo, resolved = _resolve_cbo(
        facts.couplings,
        facts.typed_couplings,
        class_name=class_node.name,
        module_class_names={"Sample", "Local"},
        imported_binding_names={"External", "Helper"},
    )
    # Helper: parameter and `list[Helper]` annotation (imported-domain lane).
    # Local: class of this module, instantiated (local lane).
    # External is an imported BASE, which the edge contract excludes; the old
    # any-position rule could not count it either, because production supplied
    # module names ("ext"), never symbol names, to this parameter.
    assert cbo == 2
    assert resolved == ("Helper", "Local")


def test_resolve_cbo_imported_lane_counts_only_type_positions() -> None:
    """The imported-domain lane is a position rule, not name membership.

    Negative twin for the Y6 edge contract: every name below is an imported
    binding, but only those in a type-collaboration position are edges. A bare
    reference (``marker``) and a module binding whose attribute is what gets
    used (``os``) must not produce edges — otherwise the rule would be "count
    any imported name", which is not the declared contract.
    """

    class_node = _parse_named_node(
        """
import os
from ext import Sidecar, Registry, marker

class Sample:
    def run(self, sidecar: Sidecar) -> Registry:
        os.getcwd()
        print(marker)
        return Registry()
""".strip(),
        "Sample",
    )
    assert isinstance(class_node, ast.ClassDef)
    facts = _class_walk_facts(class_node)
    cbo, resolved = _resolve_cbo(
        facts.couplings,
        facts.typed_couplings,
        class_name=class_node.name,
        module_class_names={"Sample"},
        imported_binding_names={"os", "Sidecar", "Registry", "marker"},
    )
    assert resolved == ("Registry", "Sidecar")
    assert cbo == 2


def _class_metric(
    qualname: str,
    *,
    candidates: tuple[str, ...] = (),
    coupled_classes: tuple[str, ...] = (),
) -> ClassMetrics:
    return ClassMetrics(
        qualname=qualname,
        filepath=f"{qualname.partition(':')[0].replace('.', '/')}.py",
        start_line=1,
        end_line=10,
        cbo=len(coupled_classes),
        lcom4=1,
        method_count=1,
        instance_var_count=0,
        risk_coupling=coupling_risk(len(coupled_classes)),
        risk_cohesion="low",
        coupled_classes=coupled_classes,
        instantiation_candidates=candidates,
    )


def test_annotation_lane_reads_the_attribute_of_a_dotted_annotation() -> None:
    """A dotted annotation contributes its attribute name, not the module.

    ``shortcut.Widget`` names the type ``Widget``, and ``Widget`` is not a
    binding of this module — only ``shortcut`` is — so the annotation lane
    counts nothing. This is the declared module-binding limitation of the
    edge contract, and it is the same reason ``os.getcwd()`` never makes
    ``os`` a collaborator.
    """

    class_node = _parse_named_node(
        """
import shortcut
from ext import Widget

class Sample:
    def run(self, dotted: shortcut.Widget, plain: Widget) -> None:
        self.dotted = dotted
""".strip(),
        "Sample",
    )
    assert isinstance(class_node, ast.ClassDef)

    facts = _class_walk_facts(class_node)
    cbo, resolved = _resolve_cbo(
        facts.couplings,
        facts.typed_couplings,
        class_name=class_node.name,
        module_class_names={"Sample"},
        imported_binding_names={"shortcut", "Widget"},
    )

    assert "Widget" in facts.typed_couplings
    assert resolved == ("Widget",)
    assert cbo == 1


def test_instantiation_candidates_record_only_imported_call_targets() -> None:
    """The walk emits a candidate per resolvable call target, and nothing else.

    A call target is recorded when an import of this module bound the name
    (directly, or as the module of a dotted access). A local variable's call,
    a deeper attribute chain and a call on an unbound name resolve to no
    import and are therefore not candidates at all.
    """

    class_node = _parse_named_node(
        """
class Sample:
    def run(self, factory) -> None:
        Widget()
        shortcut.Gadget()
        pkg.nested.Thing()
        factory()
        undeclared()
""".strip(),
        "Sample",
    )
    assert isinstance(class_node, ast.ClassDef)

    facts = _class_walk_facts(
        class_node,
        imported_symbol_targets={"Widget": "vendor.widgets:Widget"},
        imported_module_targets={"shortcut": "vendor.tools"},
    )

    assert sorted(facts.instantiation_candidates) == [
        "Gadget|vendor.tools:Gadget",
        "Widget|vendor.widgets:Widget",
    ]


def test_project_fold_counts_call_edges_only_on_proven_class_resolution() -> None:
    """A candidate becomes an edge exactly when its target is a known class.

    The three candidates are syntactically identical calls. Only the one whose
    target appears in the project's class index is an edge; the callee that
    resolves to a function of an analyzed module and the callee that resolves
    outside the analysis root both count zero, because neither was proven to
    be a class.
    """

    caller = _class_metric(
        "app.service:Service",
        candidates=(
            "Widget|vendor.widgets:Widget",
            "render|vendor.widgets:render",
            "Remote|thirdparty.sdk:Remote",
        ),
    )
    widget = _class_metric("vendor.widgets:Widget")

    resolved = {
        metric.qualname: metric
        for metric in resolve_project_class_coupling((caller, widget))
    }

    assert resolved["app.service:Service"].coupled_classes == ("Widget",)
    assert resolved["app.service:Service"].cbo == 1
    assert resolved["vendor.widgets:Widget"].cbo == 0


def test_project_fold_is_idempotent_and_keeps_risk_in_step() -> None:
    """Folding twice changes nothing, and the risk level follows the count."""

    caller = _class_metric(
        "app.service:Service",
        candidates=tuple(
            f"Type{index}|vendor.widgets:Type{index}" for index in range(7)
        ),
    )
    project = (
        caller,
        *(_class_metric(f"vendor.widgets:Type{index}") for index in range(7)),
    )

    once = resolve_project_class_coupling(project)
    twice = resolve_project_class_coupling(once)

    assert once == twice
    service = once[0]
    assert service.cbo == 7
    assert service.risk_coupling == coupling_risk(7)
    assert service.risk_coupling != caller.risk_coupling


def test_project_fold_depends_only_on_carried_candidates() -> None:
    """Metrics half of the cold == warm guard for the instantiation lane.

    The fold is a pure function of the facts on the class metrics, so equal
    inputs give equal output — that is what makes a warm run agree with a cold
    one. The second half of the assertion is why the cache must carry the
    candidates at all: drop them, as a wire that ignored the lane would, and
    the edge disappears. tests/test_cache.py owns the proof that the round
    trip preserves them.
    """

    widget = _class_metric("vendor.widgets:Widget")
    cold = (
        _class_metric(
            "app.service:Service",
            candidates=("Widget|vendor.widgets:Widget",),
        ),
        widget,
    )
    warm = (replace(cold[0]), replace(widget))
    stripped = (replace(cold[0], instantiation_candidates=()), widget)

    assert resolve_project_class_coupling(cold) == resolve_project_class_coupling(warm)
    assert resolve_project_class_coupling(cold)[0].coupled_classes == ("Widget",)
    assert resolve_project_class_coupling(stripped)[0].coupled_classes == ()


def test_project_fold_ignores_self_reference_and_unpacked_candidates() -> None:
    """Own name, empty labels and malformed packs never become edges."""

    caller = _class_metric(
        "app.service:Service",
        candidates=(
            "Service|app.service:Service",
            "no-separator",
            "|app.service:Service",
        ),
    )

    resolved = resolve_project_class_coupling((caller,))

    assert resolved[0].coupled_classes == ()
    assert resolved[0].cbo == 0


def test_resolve_cbo_handles_non_symbolic_variants() -> None:
    synthetic = ast.ClassDef(
        name="Sample",
        bases=[ast.Constant(value=1)],
        keywords=[],
        body=[ast.Pass()],
        decorator_list=[],
    )
    facts = _class_walk_facts(synthetic)
    cbo, resolved = _resolve_cbo(
        facts.couplings,
        facts.typed_couplings,
        class_name=synthetic.name,
        module_class_names={"Sample"},
        imported_binding_names=set(),
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
    dynamic_facts = _class_walk_facts(class_node)
    cbo_dynamic, resolved_dynamic = _resolve_cbo(
        dynamic_facts.couplings,
        dynamic_facts.typed_couplings,
        class_name=class_node.name,
        module_class_names={"DynamicCalls"},
        imported_binding_names={"External"},
    )
    assert cbo_dynamic == 0
    assert resolved_dynamic == ()


def test_coupling_risk_boundaries() -> None:
    """Both band edges, asserted at the boundary each one governs.

    39Y item 3 re-derived the edges from the measured CBO distribution (p90 and
    p95; they were 5 and 10), which tightened both: strictly more classes read
    as elevated and as high risk than before. The derivation and its evidence
    live in tests/test_metrics_health_recalibration.py.
    """

    assert COUPLING_RISK_LOW_MAX == 4
    assert COUPLING_RISK_MEDIUM_MAX == 7

    assert coupling_risk(COUPLING_RISK_LOW_MAX) == "low"
    assert coupling_risk(COUPLING_RISK_LOW_MAX + 1) == "medium"
    assert coupling_risk(COUPLING_RISK_MEDIUM_MAX) == "medium"
    assert coupling_risk(COUPLING_RISK_MEDIUM_MAX + 1) == "high"


def test_resolve_lcom4_for_empty_and_partially_connected_class() -> None:
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
        assert _resolve_lcom4(_class_walk_facts(class_node)) == expected


def test_resolve_lcom4_ignores_unknown_self_calls() -> None:
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
    assert _resolve_lcom4(_class_walk_facts(class_node)) == (2, 2, 1)


def test_resolve_lcom4_honors_ignored_methods() -> None:
    class_node = _parse_named_node(
        """
class Mixed:
    def connected_left(self) -> None:
        self.shared = 1
        self.connected_right()

    def connected_right(self) -> None:
        self.shared = 2

    def isolated(self) -> int:
        return 1
""".strip(),
        "Mixed",
    )
    assert isinstance(class_node, ast.ClassDef)
    assert _resolve_lcom4(_class_walk_facts(class_node)) == (2, 3, 2)
    assert _resolve_lcom4(
        _class_walk_facts(class_node, ignored_methods=frozenset({"isolated"}))
    ) == (
        1,
        3,
        2,
    )
    assert _resolve_lcom4(
        _class_walk_facts(
            class_node,
            ignored_methods=frozenset(
                {"connected_left", "connected_right", "isolated"},
            ),
        )
    ) == (1, 3, 0)


def test_class_walk_fuses_partitioned_coupling_and_cohesion_facts() -> None:
    class_node = _parse_named_node(
        """
@decorate(External)
class Fused(Base, metaclass=Factory):
    field: Helper

    class Nested:
        def nested(self) -> None:
            self.nested_only = Local()

    def left(self, value: Input) -> None:
        self.shared = value
        self.right()

    def right(self) -> None:
        self.shared = Output()
        cls.external()
""".strip(),
        "Fused",
    )
    assert isinstance(class_node, ast.ClassDef)

    facts = _class_walk_facts(class_node)

    assert facts.all_method_count == 2
    assert facts.method_to_attrs == {
        "left": {"right", "shared"},
        "right": {"shared"},
    }
    assert facts.method_calls == {"left": {"right"}, "right": set()}
    assert {
        "Base",
        "External",
        "Factory",
        "Helper",
        "Input",
        "Local",
        "Output",
        "decorate",
        "external",
    } <= facts.couplings


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


def test_source_kind_uses_importable_package_identity_for_test_named_trees() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "source_kind"
    ground_truth = json.loads((fixture_root / "ground_truth.json").read_text())
    registries = {
        layout: build_test_module_registry(
            root=fixture_root / layout,
            source_roots=tuple(source_roots),
        )
        for layout, source_roots in ground_truth["layout_source_roots"].items()
    }

    observed = {}
    for case in ground_truth["cases"]:
        layout, relative_path = case["path"].split("/", maxsplit=1)
        observed[case["id"]] = classify_source_kind(
            relative_path,
            module_registry=registries[layout],
        )

    assert observed == {
        case["id"]: case["expected"]["source_kind"] for case in ground_truth["cases"]
    }

    # Every declared negative twin must actually discriminate or, where both
    # sides share a verdict, prove the rule stays silent outside its predicate.
    for left, right in ground_truth["negative_twins"]:
        assert f"{left}|{right}" in ground_truth["twin_axes"]
    for left, right in ground_truth["rename_twins"]:
        assert observed[left] == observed[right]
        assert f"{left}|{right}" in ground_truth["twin_axes"]

    assert SOURCE_KIND_POLICY_VERSION == "1"


def test_dead_item_rejects_incoherent_test_reference_evidence() -> None:
    source = "tests.test_mod:test_helper"

    def build(
        reason: Literal["unreferenced", "test_only_reference"] = "unreferenced",
        sources: tuple[str, ...] = (),
    ) -> DeadItem:
        return DeadItem(
            qualname="pkg.mod:helper",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            confidence="high",
            reason=reason,
            test_reference_sources=sources,
        )

    with pytest.raises(ValueError, match="sorted and unique"):
        build("test_only_reference", (source, source))
    with pytest.raises(ValueError, match="sorted and unique"):
        build("test_only_reference", ("tests.b:t", "tests.a:t"))
    with pytest.raises(ValueError, match="requires test reference sources"):
        build("test_only_reference", ())
    with pytest.raises(ValueError, match="cannot have test reference sources"):
        build("unreferenced", (source,))

    accepted = build("test_only_reference", (source,))
    assert accepted.test_reference_sources == (source,)
    assert build().reason == "unreferenced"


def test_source_kind_vocabulary_preserves_filename_rules() -> None:
    assert classify_source_kind("tests/unit/helpers.py") == "tests"
    assert classify_source_kind("test/unit/helpers.py") == "tests"
    assert classify_source_kind("testing/unit/helpers.py") == "tests"
    assert classify_source_kind("tests/fixtures/payload.py") == "fixtures"
    assert is_test_filepath("src/example/conftest.py") is True
    assert is_test_filepath("src/example/test_helpers.py") is True


def test_dead_code_uses_module_identity_for_test_named_package_trees() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "source_kind"
    package_candidate = DeadCandidate(
        qualname="example.testing.helpers:unused",
        local_name="unused",
        filepath="src/example/testing/helpers.py",
        start_line=1,
        end_line=2,
        kind="function",
    )
    package_registry = build_test_module_registry(
        root=fixture_root / "in_package",
        source_roots=("src",),
    )
    assert find_unused(
        definitions=(package_candidate,),
        referenced_names=frozenset(),
        module_registry=package_registry,
    ) == (
        DeadItem(
            qualname=package_candidate.qualname,
            filepath=package_candidate.filepath,
            start_line=1,
            end_line=2,
            kind="function",
            confidence="high",
        ),
    )

    test_candidate = DeadCandidate(
        qualname="testing.case:unused",
        local_name="unused",
        filepath="testing/case.py",
        start_line=1,
        end_line=2,
        kind="function",
    )
    test_registry = build_test_module_registry(root=fixture_root / "repo_root")
    assert (
        find_unused(
            definitions=(test_candidate,),
            referenced_names=frozenset(),
            module_registry=test_registry,
        )
        == ()
    )


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
    assert cycles == (("a", "b"),)
    assert max_depth(graph) >= 2
    assert longest_chains(graph, limit=0) == ()
    assert longest_chains(graph, limit=2)


def test_build_dep_graph_deduplicates_edges() -> None:
    repeated = ModuleDep(source="pkg.a", target="pkg.b", import_type="import", line=1)
    external = ModuleDep(source="pkg.a", target="typing", import_type="import", line=2)
    registry = module_registry_context(
        filepath="pkg/a.py",
        module_name="pkg.a",
        inventory_modules=("pkg.b",),
    )[1]
    dep_graph = build_dep_graph(registry=registry, deps=(repeated, repeated, external))
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
            elevated_complexity_functions=0,
            complexity_function_population=0,
            coupling_avg=20.0,
            coupling_max=50,
            high_risk_classes=10,
            elevated_coupling_classes=25,
            coupling_class_population=40,
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


def test_depth_profile_empty_graph_returns_zeros() -> None:
    avg_depth, p95_depth = depth_profile({})
    assert avg_depth == 0.0
    assert p95_depth == 0


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
            elevated_complexity_functions=0,
            complexity_function_population=0,
            coupling_avg=0.0,
            coupling_max=0,
            high_risk_classes=0,
            elevated_coupling_classes=0,
            coupling_class_population=0,
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


def test_select_dependency_graph_nodes_small_graph_keeps_all() -> None:
    nodes, filtered, truncation = select_dependency_graph_nodes(
        [("a", "b"), ("b", "c")],
        dep_cycles=[],
        longest_chains=[],
        max_nodes=20,
        max_edges=100,
    )
    assert nodes == ["a", "b", "c"]
    assert filtered == [("a", "b"), ("b", "c")]
    assert truncation == {
        "truncated": False,
        "node_universe_count": 3,
        "node_shown_count": 3,
        "edge_universe_count": 2,
        "edge_shown_count": 2,
        "seed_policy": "cycles_then_chains_then_degree",
    }


def test_select_dependency_graph_nodes_seeds_cycles_chains_then_degree() -> None:
    edges = [
        ("h", "a"),
        ("h", "b"),
        ("h", "c"),
        ("h", "d"),
        ("x", "y"),
        ("y", "x"),
    ]
    nodes, filtered, truncation = select_dependency_graph_nodes(
        edges,
        dep_cycles=[["x", "y"]],
        longest_chains=[["d"]],
        max_nodes=4,
        max_edges=100,
    )
    # Cycle members and the chain member survive downsampling even though they
    # are lower-degree than the hub; the hub fills the last slot by degree.
    assert nodes == ["d", "h", "x", "y"]
    assert truncation["truncated"] is True
    assert truncation["node_universe_count"] == 7
    assert truncation["node_shown_count"] == 4
    assert ("h", "d") in filtered
    assert ("x", "y") in filtered and ("y", "x") in filtered


def test_select_dependency_graph_nodes_node_id_fn_seeds_by_zoom_id() -> None:
    def to_package(module: str) -> str:
        return module.split(":", 1)[0]

    nodes, _filtered, truncation = select_dependency_graph_nodes(
        [("p0", "p1"), ("p0", "p2"), ("p0", "p3"), ("p4", "p5")],
        dep_cycles=[["p5:m1", "p5:m2"]],
        longest_chains=[],
        max_nodes=2,
        max_edges=100,
        node_id_fn=to_package,
    )
    # The module-level cycle node "p5:m1" maps to package id "p5" before the
    # membership check, so the package survives the seed pass.
    assert nodes == ["p0", "p5"]
    assert truncation["truncated"] is True


def test_select_dependency_graph_nodes_caps_edges_without_node_truncation() -> None:
    nodes, filtered, truncation = select_dependency_graph_nodes(
        [("a", "b"), ("b", "c"), ("c", "a"), ("a", "c")],
        dep_cycles=[],
        longest_chains=[],
        max_nodes=20,
        max_edges=2,
    )
    assert nodes == ["a", "b", "c"]
    assert filtered == [("a", "b"), ("b", "c")]
    assert truncation["truncated"] is True
    assert truncation["node_shown_count"] == 3
    assert truncation["edge_universe_count"] == 4
    assert truncation["edge_shown_count"] == 2


def _rule_three_class_metrics(
    *,
    qualname: str,
    base_names: tuple[str, ...] = (),
    has_unresolved_external_base: bool = False,
    decorator_evidenced_methods: tuple[str, ...] = (),
) -> ClassMetrics:
    """A ClassMetrics carrying only the rule-3 facts under test.

    The coupling/cohesion numbers are inert here: rule 3 reads the base and
    decorator facts, never the metrics that share the carrier.
    """
    return ClassMetrics(
        qualname=qualname,
        filepath="x.py",
        start_line=1,
        end_line=2,
        cbo=0,
        lcom4=1,
        method_count=1,
        instance_var_count=0,
        risk_coupling="low",
        risk_cohesion="low",
        base_names=base_names,
        has_unresolved_external_base=has_unresolved_external_base,
        decorator_evidenced_methods=decorator_evidenced_methods,
    )


def test_decorator_evidence_makes_an_opaque_base_method_live() -> None:
    """Rule-3 decision table row 2: an explicit dispatch contract is LIVE.

    The shipped code only used decorator evidence to DENY the abstention, then
    fell through to the dead branch — so ``@override`` produced a dead finding,
    the exact inverse of the ruled table. Evidence must skip the symbol.

    The local-shim form is what makes the inversion reachable in production: a
    decorator named ``override`` imported from a LOCAL module carries row-2
    evidence without being an external decorator, so the external-decorator
    root never shields it and the symbol reaches this branch.
    """

    definitions = (
        DeadCandidate(
            qualname="pkg.mod:ShimHandler.process",
            local_name="process",
            filepath="pkg/mod.py",
            start_line=2,
            end_line=3,
            kind="method",
        ),
    )

    def classify(evidenced: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        result = classify_liveness(
            definitions=definitions,
            referenced_names=frozenset(),
            class_metrics=(
                _rule_three_class_metrics(
                    qualname="pkg.mod:ShimHandler",
                    base_names=("Handler",),
                    has_unresolved_external_base=True,
                    decorator_evidenced_methods=evidenced,
                ),
            ),
        )
        return (
            tuple(item.qualname for item in result.dead_items),
            tuple(item.qualname for item in result.unresolved_overrides),
        )

    dead, abstained = classify(("pkg.mod:ShimHandler.process",))
    assert dead == (), f"row 2 evidence must not produce a dead finding: {dead}"
    assert abstained == (), f"row 2 evidence is live, not an abstention: {abstained}"

    # Contrast: the same method WITHOUT evidence abstains. This pins that the
    # decorator fact is the discriminator, not the opaque base alone.
    dead_unevidenced, abstained_unevidenced = classify(())
    assert dead_unevidenced == ()
    assert abstained_unevidenced == ("pkg.mod:ShimHandler.process",)


def test_tri_state_liveness_is_stable_and_the_bypass_stays_narrow() -> None:
    """39J guard, metrics half: equal facts give equal statuses.

    The cache half (tests/test_cache.py) proves the 3.2 wire returns a warm
    run exactly the facts a cold run computed. This half proves the verdict is
    a pure function of those facts, so cold and warm agree, and pins the
    narrowness of the rule-3 bypass: the SAME bare method name still revives
    the local-base method through the untouched name gate, while only the
    external-base sibling abstains.
    """
    definitions = (
        DeadCandidate(
            qualname="x:Adapter.handle",
            local_name="handle",
            filepath="x.py",
            start_line=4,
            end_line=5,
            kind="method",
        ),
        DeadCandidate(
            qualname="x:LocalOnly.handle",
            local_name="handle",
            filepath="x.py",
            start_line=8,
            end_line=9,
            kind="method",
        ),
    )
    class_metrics = (
        _rule_three_class_metrics(
            qualname="x:Adapter",
            base_names=("Base",),
            has_unresolved_external_base=True,
        ),
        _rule_three_class_metrics(
            qualname="x:LocalOnly",
            base_names=("object",),
            has_unresolved_external_base=False,
        ),
    )

    def classify() -> tuple[tuple[str, ...], tuple[str, ...]]:
        result = classify_liveness(
            definitions=definitions,
            referenced_names=frozenset({"handle"}),
            class_metrics=class_metrics,
        )
        return (
            tuple(item.qualname for item in result.dead_items),
            tuple(item.qualname for item in result.unresolved_overrides),
        )

    dead, unresolved = classify()
    # Repeating the call on identical facts is the cold-vs-warm equality.
    assert classify() == (dead, unresolved)

    assert unresolved == ("x:Adapter.handle",)
    # LocalOnly.handle is neither dead nor abstaining: the shared bare name
    # still revives it, because the bypass touches only opaque-base methods.
    assert dead == ()


def test_builtin_name_registry_is_interpreter_pinned() -> None:
    """CBO's builtin exclusion is a pinned fact source, not ``dir(builtins)``.

    The same repository must yield the same coupling facts on every supported
    interpreter (G5, Python 3.15 probe). The registry therefore pins the union
    of builtin names across CPython 3.10-3.15; names that become builtins only
    on newer interpreters are excluded everywhere, not just where they exist.
    """

    import builtins

    from codeclone.metrics.coupling import _BUILTIN_NAMES

    # 3.15-only builtins are excluded on every interpreter.
    assert {
        "ImportCycleError",
        "__lazy_import__",
        "frozendict",
        "sentinel",
    } <= _BUILTIN_NAMES
    # 3.11+/3.13+ additions stay covered on the 3.10 leg.
    assert {"BaseExceptionGroup", "ExceptionGroup", "PythonFinalizationError"} <= (
        _BUILTIN_NAMES
    )
    # Bump tripwire: a running interpreter whose builtins outgrow the pinned
    # registry means a new CPython joined the matrix without a registry review.
    assert set(dir(builtins)) <= _BUILTIN_NAMES
