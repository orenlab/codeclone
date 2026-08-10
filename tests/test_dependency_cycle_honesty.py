# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cycle honesty laws, pinned red-first.

Two maintainer-ratified laws ride here together:

1. Path honesty — a dependency-cycle finding never invents a module path.
   ``<pkg>/__init__.py`` when it exists, else ``<pkg>.py`` when it exists,
   else UNRESOLVED; one owner in ``codeclone.paths.module_identity``.
2. Binding honesty — every dependency edge carries its statically derived
   binding time, and a cycle is ``import_cycle`` (critical) iff the subgraph
   restricted to import-time edges still contains a cycle; otherwise it is
   ``deferred_cycle`` (warning). TYPE_CHECKING edges are excluded from
   runtime cycles entirely while staying visible as edges.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path

import pytest

from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.cache.entries import _module_dep_dict_from_model
from codeclone.core.discovery_cache import _module_dep_from_cache_row
from codeclone.metrics.dependencies import build_dep_graph
from codeclone.models import ModuleDep, ModuleRegistryHandle
from codeclone.qualnames import QualnameCollector
from tests._ast_metrics_helpers import module_registry_context

FIXTURES = Path(__file__).parent / "fixtures"


def _walk(
    source: str,
    *,
    module_name: str,
    inventory: tuple[str, ...] = (),
) -> tuple[ast.Module, module_walk_mod._ModuleWalkResult]:
    identity, registry = module_registry_context(
        filepath=f"{module_name.replace('.', '/')}.py",
        module_name=module_name,
        inventory_modules=inventory,
    )
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    return tree, module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )


def _deps_by_target(
    walk: module_walk_mod._ModuleWalkResult,
) -> dict[str, ModuleDep]:
    return {dep.target: dep for dep in walk.module_deps}


# ---------------------------------------------------------------------------
# Edge binding classification (Fix 2, collection law)
# ---------------------------------------------------------------------------


def test_walk_classifies_edge_binding_by_position() -> None:
    _tree, walk = _walk(
        """
import top_level
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typing_only


def helper():
    import inside_function


def __getattr__(name):
    import inside_getattr
""".strip(),
        module_name="mod",
    )
    deps = _deps_by_target(walk)
    assert deps["top_level"].binding == "import_time"
    assert deps["typing_only"].binding == "type_checking"
    assert deps["inside_function"].binding == "deferred_function"
    assert deps["inside_getattr"].binding == "deferred_getattr"
    assert all(dep.is_lazy is False for dep in walk.module_deps)


def test_walk_classifies_class_body_import_as_import_time() -> None:
    _tree, walk = _walk(
        """
class Holder:
    import in_class_body
""".strip(),
        module_name="mod",
    )
    assert _deps_by_target(walk)["in_class_body"].binding == "import_time"


def test_walk_classifies_method_import_as_deferred_function() -> None:
    _tree, walk = _walk(
        """
class Holder:
    def load(self):
        import in_method
""".strip(),
        module_name="mod",
    )
    assert _deps_by_target(walk)["in_method"].binding == "deferred_function"


def test_nested_getattr_helper_is_not_a_module_getattr() -> None:
    """Only the MODULE-level ``__getattr__`` defers through the PEP 562 hook."""

    _tree, walk = _walk(
        """
class Holder:
    def __getattr__(self, name):
        import in_instance_getattr
""".strip(),
        module_name="mod",
    )
    assert _deps_by_target(walk)["in_instance_getattr"].binding == "deferred_function"


def test_walk_reads_pep810_lazy_marker_as_lazy_syntax() -> None:
    """PEP 810 ``lazy import`` — statically derived from the AST marker.

    Older interpreters cannot parse the keyword, so the marker is stamped on
    the node exactly the way a 3.15 parser (or the wire decoder) presents it.
    """

    tree = ast.parse("import lazily_bound")
    vars(tree.body[0])["is_lazy"] = True
    identity, registry = module_registry_context(
        filepath="mod.py",
        module_name="mod",
    )
    collector = QualnameCollector()
    collector.visit(tree)
    walk = module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )
    dep = _deps_by_target(walk)["lazily_bound"]
    assert dep.binding == "lazy_syntax"
    assert dep.is_lazy is True


def test_dynamic_load_binding_follows_recorded_scope() -> None:
    _tree, walk = _walk(
        """
import importlib

importlib.import_module("eager_dynamic")


def loader():
    importlib.import_module("lazy_dynamic")
""".strip(),
        module_name="mod",
    )
    deps = _deps_by_target(walk)
    assert deps["eager_dynamic"].binding == "import_time"
    assert deps["eager_dynamic"].mechanism == "dynamic"
    assert deps["lazy_dynamic"].binding == "deferred_function"
    assert deps["lazy_dynamic"].mechanism == "dynamic"


# ---------------------------------------------------------------------------
# Cycle law (Fix 2, graph law)
# ---------------------------------------------------------------------------


def _dep(
    source: str,
    target: str,
    *,
    binding: str = "import_time",
    line: int = 1,
) -> ModuleDep:
    return ModuleDep(
        source=source,
        target=target,
        import_type="import",
        line=line,
        resolution="analyzed",
        requested_module=target,
        candidate_targets=(target,),
        binding=binding,  # type: ignore[arg-type]
    )


def _registry_for(*modules: str) -> ModuleRegistryHandle:
    first, *rest = modules
    return module_registry_context(
        filepath=f"{first.replace('.', '/')}.py",
        module_name=first,
        inventory_modules=tuple(rest),
    )[1]


def test_import_time_cycle_classifies_as_import_cycle() -> None:
    registry = _registry_for("a", "b")
    graph = build_dep_graph(
        registry=registry,
        deps=(_dep("a", "b"), _dep("b", "a")),
    )
    assert graph.cycles == (("a", "b"),)
    assert [detail.kind for detail in graph.cycle_details] == ["import_cycle"]


@pytest.mark.parametrize(
    ("forward_binding", "backward_binding"),
    [
        ("deferred_function", "deferred_getattr"),
        ("lazy_syntax", "lazy_syntax"),
    ],
)
def test_deferred_only_cycle_classifies_as_deferred_cycle(
    forward_binding: str,
    backward_binding: str,
) -> None:
    registry = _registry_for("a", "b")
    graph = build_dep_graph(
        registry=registry,
        deps=(
            _dep("a", "b", binding=forward_binding),
            _dep("b", "a", binding=backward_binding),
        ),
    )
    assert graph.cycles == (("a", "b"),)
    assert [detail.kind for detail in graph.cycle_details] == ["deferred_cycle"]


def test_mixed_cycle_with_import_time_subcycle_stays_critical() -> None:
    """A wider SCC is critical when ANY import-time subcycle survives."""

    registry = _registry_for("a", "b", "c")
    graph = build_dep_graph(
        registry=registry,
        deps=(
            _dep("a", "b"),
            _dep("b", "a"),
            _dep("b", "c", binding="deferred_function"),
            _dep("c", "a", binding="deferred_function"),
            _dep("a", "c", binding="deferred_function"),
        ),
    )
    assert graph.cycles == (("a", "b", "c"),)
    assert [detail.kind for detail in graph.cycle_details] == ["import_cycle"]


def test_mixed_cycle_without_import_time_subcycle_is_deferred() -> None:
    """Import-time edges that do not themselves cycle defuse the crash risk."""

    registry = _registry_for("a", "b")
    graph = build_dep_graph(
        registry=registry,
        deps=(
            _dep("a", "b"),
            _dep("b", "a", binding="deferred_function"),
        ),
    )
    assert graph.cycles == (("a", "b"),)
    assert [detail.kind for detail in graph.cycle_details] == ["deferred_cycle"]


def test_type_checking_edges_never_form_runtime_cycles() -> None:
    registry = _registry_for("a", "b")
    graph = build_dep_graph(
        registry=registry,
        deps=(
            _dep("a", "b", binding="type_checking"),
            _dep("b", "a"),
        ),
    )
    assert graph.cycles == ()
    assert graph.cycle_details == ()
    # The typing edge stays visible in the edge list — no data thrown away.
    assert {(dep.source, dep.target, dep.binding) for dep in graph.edges} == {
        ("a", "b", "type_checking"),
        ("b", "a", "import_time"),
    }


# ---------------------------------------------------------------------------
# Module-path projection owner (Fix 1, path law)
# ---------------------------------------------------------------------------


def test_projection_owner_prefers_package_init() -> None:
    from codeclone.paths.module_identity.projection import module_path_from_files

    files = frozenset({"pkg/__init__.py", "pkg/util/__init__.py", "pkg/util.py"})
    # Package layout wins even when a same-named module file exists.
    assert module_path_from_files("pkg.util", files) == "pkg/util/__init__.py"
    assert module_path_from_files("pkg", files) == "pkg/__init__.py"


def test_projection_owner_falls_back_to_module_file() -> None:
    from codeclone.paths.module_identity.projection import module_path_from_files

    files = frozenset({"pkg/__init__.py", "pkg/mod.py"})
    assert module_path_from_files("pkg.mod", files) == "pkg/mod.py"


def test_projection_owner_never_invents_a_path() -> None:
    from codeclone.paths.module_identity.projection import module_path_from_files

    assert module_path_from_files("ghost.module", frozenset()) is None
    assert module_path_from_files("", frozenset({"a.py"})) is None


def test_projection_owner_resolves_against_a_real_root(tmp_path: Path) -> None:
    from codeclone.paths.module_identity.projection import module_path_under_root

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "solo.py").write_text("", encoding="utf-8")
    assert module_path_under_root("pkg", tmp_path) == "pkg/__init__.py"
    assert module_path_under_root("solo", tmp_path) == "solo.py"
    assert module_path_under_root("ghost", tmp_path) is None


def test_dep_graph_resolves_cycle_member_paths_from_registry() -> None:
    """Registry identity is the projection truth — layouts never guessed."""

    _identity, registry = module_registry_context(
        filepath="pkga/__init__.py",
        module_name="pkga",
        inventory_modules=("modb",),
    )
    graph = build_dep_graph(
        registry=registry,
        deps=(_dep("pkga", "modb"), _dep("modb", "pkga")),
    )
    assert graph.cycles == (("modb", "pkga"),)
    (detail,) = graph.cycle_details
    assert detail.modules == ("modb", "pkga")
    assert detail.member_paths == ("modb.py", "pkga/__init__.py")


# ---------------------------------------------------------------------------
# Cache wire codec (one coordinated dependencies lane bump)
# ---------------------------------------------------------------------------


def test_module_dep_cache_row_roundtrips_binding_and_laziness() -> None:
    dep = ModuleDep(
        source="mod",
        target="other",
        import_type="import",
        line=7,
        resolution="analyzed",
        requested_module="other",
        candidate_targets=("other",),
        binding="deferred_function",
        is_lazy=False,
    )
    row = _module_dep_dict_from_model(dep)
    assert row["binding"] == "deferred_function"
    assert row["is_lazy"] is False
    assert _module_dep_from_cache_row(row) == dep


def test_module_dep_wire_row_roundtrips_binding_and_laziness() -> None:
    from codeclone.cache._wire_decode import _decode_wire_module_dep

    dep = ModuleDep(
        source="mod",
        target="other",
        import_type="import",
        line=3,
        resolution="analyzed",
        requested_module="other",
        candidate_targets=("other",),
        binding="lazy_syntax",
        is_lazy=True,
    )
    row = _module_dep_dict_from_model(dep)
    wire_row = [
        row["source"],
        row["target"],
        row["import_type"],
        row["line"],
        row["resolution"],
        row["inventory_expansion"],
        row["level"],
        row["requested_module"],
        row["requested_names"],
        row["candidate_targets"],
        row["mechanism"],
        row["binding"],
        row["is_lazy"],
    ]
    decoded = _decode_wire_module_dep(wire_row)
    assert decoded is not None
    assert decoded["binding"] == "lazy_syntax"
    assert decoded["is_lazy"] is True
    assert _module_dep_from_cache_row(decoded) == dep


def test_legacy_wire_rows_decode_to_eager_defaults() -> None:
    """A pre-bump 11-column row still decodes; defaults mean eager."""

    from codeclone.cache._wire_decode import _decode_wire_module_dep

    legacy_row = [
        "mod",
        "other",
        "import",
        3,
        "analyzed",
        False,
        0,
        "other",
        [],
        ["other"],
        "static",
    ]
    decoded = _decode_wire_module_dep(legacy_row)
    assert decoded is not None
    dep = _module_dep_from_cache_row(decoded)
    assert dep is not None
    assert dep.binding == "import_time"
    assert dep.is_lazy is False


# ---------------------------------------------------------------------------
# End-to-end over the fixture corpora (both laws in one report)
# ---------------------------------------------------------------------------


def _analyze_fixture_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tree_name: str,
) -> tuple[Path, dict[str, object]]:
    import codeclone.surfaces.cli.workflow as cli

    project_root = tmp_path / tree_name
    project_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / tree_name, project_root)
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(project_root),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--cache-path",
            str(tmp_path / "cache.json"),
            "--json",
            str(report_path),
            # Metrics are silently skipped when nothing requests them and no
            # metrics baseline exists; the dependency family needs them on.
            "--no-skip-metrics",
            "--no-progress",
        ],
    )
    cli.main()
    return project_root, json.loads(report_path.read_text("utf-8"))


def _dependency_groups(payload: dict[str, object]) -> list[dict[str, object]]:
    findings = payload.get("findings")
    assert isinstance(findings, dict)
    families = findings.get("groups")
    assert isinstance(families, dict)
    design = families.get("design")
    assert isinstance(design, dict)
    groups = design.get("groups")
    assert isinstance(groups, list)
    return [
        group
        for group in groups
        if isinstance(group, dict) and group.get("category") == "dependency"
    ]


def _group_items(group: dict[str, object]) -> list[dict[str, object]]:
    items = group.get("items")
    assert isinstance(items, list)
    return [item for item in items if isinstance(item, dict)]


def test_cycle_finding_reports_only_paths_that_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root, payload = _analyze_fixture_tree(
        monkeypatch,
        tmp_path,
        "cycle_path_projection",
    )
    groups = _dependency_groups(payload)
    assert len(groups) == 1, groups
    (group,) = groups
    items = group.get("items")
    assert isinstance(items, list) and items
    reported = {
        str(item.get("module", "")): str(item.get("relative_path", ""))
        for item in items
        if isinstance(item, dict)
    }
    assert reported == {
        "modb": "modb.py",
        "pkga": "pkga/__init__.py",
    }
    for relative_path in reported.values():
        assert (project_root / relative_path).is_file(), relative_path


def test_cycle_findings_split_by_binding_law(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root, payload = _analyze_fixture_tree(
        monkeypatch,
        tmp_path,
        "dependency_binding",
    )
    groups = _dependency_groups(payload)
    by_kind = {str(group.get("kind")): group for group in groups}
    assert set(by_kind) == {"import_cycle", "deferred_cycle"}, sorted(by_kind)

    import_group = by_kind["import_cycle"]
    assert import_group.get("severity") == "critical"
    import_members = {str(item.get("module")) for item in _group_items(import_group)}
    assert import_members == {"eag_one", "eag_two"}

    deferred_group = by_kind["deferred_cycle"]
    assert deferred_group.get("severity") == "warning"
    deferred_members = {
        str(item.get("module")) for item in _group_items(deferred_group)
    }
    assert deferred_members == {"defa", "defb"}

    # The typing-only pair must not surface as any cycle at all.
    all_members = {
        str(item.get("module")) for group in groups for item in _group_items(group)
    }
    assert "tca" not in all_members
    assert "tcb" not in all_members

    # Path honesty holds across every reported member.
    for group in groups:
        for item in _group_items(group):
            relative_path = str(item.get("relative_path", ""))
            assert relative_path, item
            assert (project_root / relative_path).is_file(), relative_path


def test_dependency_findings_are_deterministic_across_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _root_one, payload_one = _analyze_fixture_tree(
        monkeypatch,
        tmp_path / "one",
        "dependency_binding",
    )
    _root_two, payload_two = _analyze_fixture_tree(
        monkeypatch,
        tmp_path / "two",
        "dependency_binding",
    )
    groups_one = json.dumps(_dependency_groups(payload_one), sort_keys=True)
    groups_two = json.dumps(_dependency_groups(payload_two), sort_keys=True)
    assert groups_one == groups_two
