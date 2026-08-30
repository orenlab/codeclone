# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal, cast

from codeclone.metrics import api_surface as api_surface_mod
from codeclone.metrics._visibility import ModuleVisibility
from codeclone.metrics.api_surface import (
    collect_module_api_surface,
    compare_api_surfaces,
    is_product_api_module,
    product_api_modules,
)
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    ModuleApiSurface,
    PublicSymbol,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._ast_metrics_helpers import tree_collector_and_imports
from tests._pipeline_fixtures import PipelineRun, analysis_boot, run_pipeline_once

from .ast_test_helpers import parse_class_first_member


def test_collect_module_api_surface_skips_self_and_collects_public_symbols() -> None:
    tree, collector, import_names = tree_collector_and_imports(
        """
__all__ = ["run", "Public", "VALUE"]

def run(value: int, *, enabled: bool = True) -> int:
    return value

class Public:
    def __init__(self, dep, *, lazy: bool = False) -> None:
        self.dep = dep

    def method(self, item: str) -> None:
        return None

    def _hidden(self, value: int) -> None:
        return None

VALUE = 1
""",
        module_name="pkg.mod",
    )

    surface = collect_module_api_surface(
        tree=tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=collector,
        imported_names=import_names,
    )

    assert surface is not None
    assert surface.module == "pkg.mod"
    assert [symbol.qualname for symbol in surface.symbols] == [
        "pkg.mod:Public",
        "pkg.mod:Public.__init__",
        "pkg.mod:Public.method",
        "pkg.mod:VALUE",
        "pkg.mod:run",
    ]
    init_symbol = next(
        symbol
        for symbol in surface.symbols
        if symbol.qualname == "pkg.mod:Public.__init__"
    )
    method_symbol = next(
        symbol
        for symbol in surface.symbols
        if symbol.qualname == "pkg.mod:Public.method"
    )
    assert [param.name for param in init_symbol.params] == ["dep", "lazy"]
    assert [param.name for param in method_symbol.params] == ["item"]

    run_symbol = next(
        symbol for symbol in surface.symbols if symbol.qualname == "pkg.mod:run"
    )
    component_digests = (
        *(parameter.annotation_hash for parameter in run_symbol.params),
        run_symbol.returns_hash,
    )
    assert all(len(value) == 64 for value in component_digests)
    assert all(set(value) <= set("0123456789abcdef") for value in component_digests)


def test_api_signature_component_digests_are_parse_stable() -> None:
    source = """
__all__ = ["run"]

def run(left: list[str], /, right: dict[str, int] | None = None) -> tuple[str, ...]:
    return tuple(left)
"""
    first_tree, first_collector, first_imports = tree_collector_and_imports(
        source,
        module_name="pkg.mod",
    )
    second_tree, second_collector, second_imports = tree_collector_and_imports(
        source,
        module_name="pkg.mod",
    )

    first = collect_module_api_surface(
        tree=first_tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=first_collector,
        imported_names=first_imports,
    )
    second = collect_module_api_surface(
        tree=second_tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=second_collector,
        imported_names=second_imports,
    )

    assert first == second
    assert first is not None
    symbol = first.symbols[0]
    assert tuple(parameter.name for parameter in symbol.params) == ("left", "right")
    assert tuple(parameter.annotation_hash for parameter in symbol.params) == (
        "d848e7ea6a2971377d41e7d72f4c7e0f0bf543e857fe1d5a287ba6d5e87d8d8f",
        "6973abc818e5033a061453bfc60e8cfd53c69d48e60c751c06bab4e647b9fc5a",
    )
    assert (
        symbol.returns_hash
        == "482d6d649923a7350f54e3b1d64b23be713f87ba712c546ffe99493fc627479d"
    )


def test_compare_api_surfaces_reports_added_removed_and_signature_breaks() -> None:
    baseline = ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=3,
                        params=(
                            ApiParamSpec(
                                name="value",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="limit",
                                kind="pos_or_kw",
                                has_default=True,
                            ),
                        ),
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:gone",
                        kind="function",
                        start_line=5,
                        end_line=6,
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:Public.method",
                        kind="method",
                        start_line=10,
                        end_line=12,
                        params=(
                            ApiParamSpec(
                                name="enabled",
                                kind="kw_only",
                                has_default=True,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    current = ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:added",
                        kind="function",
                        start_line=20,
                        end_line=21,
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=3,
                        params=(
                            ApiParamSpec(
                                name="value",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="amount",
                                kind="pos_or_kw",
                                has_default=True,
                            ),
                        ),
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:Public.method",
                        kind="method",
                        start_line=10,
                        end_line=12,
                        params=(
                            ApiParamSpec(
                                name="enabled",
                                kind="kw_only",
                                has_default=False,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    added, breaking = compare_api_surfaces(
        baseline=baseline,
        current=current,
        strict_types=False,
    )

    assert added == ("pkg.mod:added",)
    assert [(item.qualname, item.change_kind) for item in breaking] == [
        ("pkg.mod:run", "signature_break"),
        ("pkg.mod:gone", "removed"),
        ("pkg.mod:Public.method", "signature_break"),
    ]
    assert breaking[0].detail == "Renamed public parameter limit to amount."
    assert breaking[1].detail == "Removed from the public API surface."
    assert breaking[2].detail == "Parameter enabled became required."


def _public_symbol(
    qualname: str,
    kind: Literal["function", "class", "method", "constant"],
    *,
    params: tuple[ApiParamSpec, ...] = (),
    returns_hash: str = "",
) -> PublicSymbol:
    return PublicSymbol(
        qualname=qualname,
        kind=kind,
        start_line=1,
        end_line=1,
        params=params,
        returns_hash=returns_hash,
    )


def test_collect_module_api_surface_skips_private_or_empty_modules() -> None:
    private_tree, private_collector, private_imports = tree_collector_and_imports(
        """
def hidden():
    return 1
""",
        module_name="pkg._internal",
    )
    assert (
        collect_module_api_surface(
            tree=private_tree,
            module_name="pkg._internal",
            filepath="pkg/_internal.py",
            collector=private_collector,
            imported_names=private_imports,
        )
        is None
    )

    empty_tree, empty_collector, empty_imports = tree_collector_and_imports(
        """
def _hidden():
    return 1
""",
        module_name="pkg.public",
    )
    assert (
        collect_module_api_surface(
            tree=empty_tree,
            module_name="pkg.public",
            filepath="pkg/public.py",
            collector=empty_collector,
            imported_names=empty_imports,
        )
        is None
    )


def test_api_surface_helpers_cover_constant_symbols_and_break_variants() -> None:
    visibility = ModuleVisibility(
        module_name="pkg.mod",
        exported_names=frozenset({"CONST", "Public"}),
        all_declared=("CONST", "Public"),
        is_public_module=True,
    )
    annassign_tree = ast.parse("CONST: int = 1")
    constant_rows = api_surface_mod._public_constant_rows(
        tree=annassign_tree,
        visibility=visibility,
    )
    assert constant_rows == (("CONST", 1, 1),)
    assign_tree = ast.parse("Public = 2")
    assign_rows = api_surface_mod._public_constant_rows(
        tree=assign_tree,
        visibility=visibility,
    )
    assert assign_rows == (("Public", 1, 1),)
    assert (
        api_surface_mod._build_public_symbol(
            module_name="pkg.mod",
            export_name="missing",
            local_name="missing",
            kind="constant",
            start_line=1,
            end_line=1,
            visibility=visibility,
        )
        is None
    )
    _outer_class, nested_class = parse_class_first_member(
        """
class Outer:
    class Inner:
        pass
""",
        ast.ClassDef,
    )
    assert (
        api_surface_mod._class_api_symbol(
            module_name="pkg.mod",
            class_qualname="Outer.Inner",
            class_node=nested_class,
            visibility=visibility,
        )
        is None
    )

    method = ast.parse(
        """
def run(self, a: int, /, b, *args: str, c: int, **kwargs: bytes) -> int:
    return 1
"""
    ).body[0]
    assert isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    params = api_surface_mod._parameter_specs(node=method, is_method=True)
    assert [param.name for param in params] == ["a", "b", "args", "c", "kwargs"]

    class_before = _public_symbol("pkg.mod:Thing", "class")
    class_after = _public_symbol("pkg.mod:Thing", "constant")
    assert (
        api_surface_mod._signature_break_detail(
            baseline_symbol=class_before,
            current_symbol=class_after,
            strict_types=False,
        )
        == "Changed public symbol kind from class to constant."
    )
    assert (
        api_surface_mod._signature_break_detail(
            baseline_symbol=class_before,
            current_symbol=_public_symbol("pkg.mod:Thing", "class"),
            strict_types=False,
        )
        is None
    )

    baseline_param = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(ApiParamSpec(name="value", kind="kw_only", has_default=False),),
    )
    current_param_kind = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(ApiParamSpec(name="value", kind="pos_or_kw", has_default=False),),
    )
    current_param_type = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(
                name="value",
                kind="kw_only",
                has_default=False,
                annotation_hash="str",
            ),
        ),
    )
    baseline_typed = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(
                name="value",
                kind="kw_only",
                has_default=False,
                annotation_hash="int",
            ),
        ),
        returns_hash="int",
    )
    current_return_type = _public_symbol(
        "pkg.mod:run",
        "function",
        params=baseline_typed.params,
        returns_hash="str",
    )
    assert "Changed parameter kind" in cast(
        str,
        api_surface_mod._signature_break_detail(
            baseline_symbol=baseline_param,
            current_symbol=current_param_kind,
            strict_types=False,
        ),
    )
    assert "Changed type annotation" in cast(
        str,
        api_surface_mod._signature_break_detail(
            baseline_symbol=baseline_typed,
            current_symbol=current_param_type,
            strict_types=True,
        ),
    )
    assert (
        api_surface_mod._signature_break_detail(
            baseline_symbol=baseline_typed,
            current_symbol=current_return_type,
            strict_types=True,
        )
        == "Changed return annotation."
    )
    fewer_params = _public_symbol("pkg.mod:run", "function", params=())
    more_params = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(name="a", kind="pos_or_kw", has_default=False),
            ApiParamSpec(name="b", kind="pos_or_kw", has_default=False),
        ),
    )
    assert (
        api_surface_mod._signature_break_detail(
            baseline_symbol=fewer_params,
            current_symbol=more_params,
            strict_types=False,
        )
        == "Changed callable parameter count."
    )


def test_symbol_index_none_snapshot_returns_empty() -> None:
    assert api_surface_mod._symbol_index(None) == {}


# ── track: the product's contract is not the repository's test code ────────


#: One tree carrying every boundary the track has to decide, as data.
#:
#: Each entry is an input that reaches a different arm of the rule, so no arm
#: of it is unreachable decoration:
#:
#: * ``pkg/mod.py`` — plain product code.
#: * ``pkg/test_helpers.py`` — a ``test_``-named module *inside* a shipped
#:   package. The source-kind owner calls the file test-kind by its name; the
#:   track follows the owner rather than second-guessing it.
#: * ``pkg/testing/tools.py`` — a ``testing`` subpackage the package really
#:   ships. Only the module registry tells it from a repository test tree,
#:   which is why the run's registry is handed to the owner.
#: * ``conftest.py`` — pytest configuration outside any test directory: the
#:   case that makes the directory rule alone insufficient.
#: * ``tests/…`` — the repository's own test tree, including a fixture tree.
#: * ``benchmarks/…`` and ``docs/conf.py`` — repository tooling. The owner
#:   calls both production, so both stay; the track invents no second rule.
_TRACK_TREE_FILES: tuple[tuple[str, str], ...] = (
    ("pkg/__init__.py", ""),
    (
        "pkg/mod.py",
        '__all__ = ["run"]\n\n\ndef run(value: int) -> int:\n    return value\n',
    ),
    ("pkg/test_helpers.py", "def helper(value: int) -> int:\n    return value\n"),
    ("pkg/testing/__init__.py", ""),
    ("pkg/testing/tools.py", "def make_client(value: int) -> int:\n    return value\n"),
    ("conftest.py", "def root_fixture(request):\n    return request\n"),
    ("tests/conftest.py", "def sample_fixture(request):\n    return request\n"),
    ("tests/test_thing.py", "def test_thing(value: int) -> None:\n    assert value\n"),
    (
        "tests/fixtures/sample.py",
        "def sample_case(value: int) -> int:\n    return value\n",
    ),
    ("benchmarks/bench_case.py", "def measure(value: int) -> int:\n    return value\n"),
    ("docs/conf.py", "def setup(app):\n    return app\n"),
)


def _mixed_track_tree(root: Path) -> None:
    """Materialize the boundary tree under ``root``."""

    for relative_path, source in _TRACK_TREE_FILES:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, "utf-8")


#: Every module the tree above publishes a public symbol from, as the run
#: names them. Stated once so the product and test halves below cannot drift
#: into two different populations.
_TRACK_TREE_SURFACES = (
    "benchmarks/bench_case.py",
    "conftest.py",
    "docs/conf.py",
    "pkg/mod.py",
    "pkg/test_helpers.py",
    "pkg/testing/tools.py",
    "tests/conftest.py",
    "tests/fixtures/sample.py",
    "tests/test_thing.py",
)

#: The product half: what a consumer asking "did the published contract
#: break" is entitled to see. Written out rather than derived, so it cannot
#: agree with a broken rule by construction.
_PRODUCT_TRACK_SURFACES = (
    "benchmarks/bench_case.py",
    "docs/conf.py",
    "pkg/mod.py",
    "pkg/testing/tools.py",
)

#: The test half, and the reason the gate was unusable.
_TEST_TRACK_SURFACES = (
    "conftest.py",
    "pkg/test_helpers.py",
    "tests/conftest.py",
    "tests/fixtures/sample.py",
    "tests/test_thing.py",
)


def _api_surface_run(root: Path, cache_path: Path) -> PipelineRun:
    _mixed_track_tree(root)
    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    boot.args.api_surface = True
    _cache, run = run_pipeline_once(boot, cache_path, root=root, warm=False)
    return run


def _metric_surfaces(run: PipelineRun, root: Path) -> list[str]:
    metrics = run.result.project_metrics
    assert metrics is not None
    # The run really produced this lane: an absent snapshot would make every
    # assertion below vacuously true.
    assert metrics.api_surface is not None
    return sorted(
        Path(module.filepath).relative_to(root).as_posix()
        for module in metrics.api_surface.modules
    )


def test_mixed_track_tree_publishes_every_boundary_case(tmp_path: Path) -> None:
    """The instrument is aimed at something.

    Each pin below asserts that some files are absent from the lane. Absence
    proves nothing about a file the collector never saw in the first place,
    so the whole population is measured once, here, without the track rule in
    the way: the collector reaches all nine.
    """

    _mixed_track_tree(tmp_path)
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=False)
    boot.args.api_surface = True
    _cache, run = run_pipeline_once(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )
    assert sorted(
        Path(module.filepath).relative_to(tmp_path).as_posix()
        for module in run.processing.api_modules
    ) == sorted(_TRACK_TREE_SURFACES)


def test_product_api_surface_metric_keeps_the_product_track(tmp_path: Path) -> None:
    """Direction one: a product symbol must not fall off the contract.

    Its opposite — a test symbol staying on the contract — is asserted by a
    separate test, so a filter that erred either way reddens a different pin
    and the two errors can never mask each other.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    surfaces = _metric_surfaces(run, tmp_path)
    assert [path for path in surfaces if path in _PRODUCT_TRACK_SURFACES] == sorted(
        _PRODUCT_TRACK_SURFACES
    )


def test_product_api_surface_metric_excludes_the_repository_test_tree(
    tmp_path: Path,
) -> None:
    """Direction two: the lane a gate reads must not carry test code.

    ``fail_on_api_break`` reads ``api_breaking_changes``, which is computed
    from this snapshot. While the snapshot carries ``tests.*``, deleting a
    test prints as ``removed | Removed from the public API surface`` and
    renaming a test parameter as ``signature_break``, so the gate is unusable
    by construction: it would fail a run for a renamed test.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    surfaces = _metric_surfaces(run, tmp_path)
    assert [path for path in surfaces if path in _TEST_TRACK_SURFACES] == []


def test_product_api_surface_metric_publishes_exactly_the_product_track(
    tmp_path: Path,
) -> None:
    """Both halves at once: nothing extra survives, nothing extra is invented."""

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    assert _metric_surfaces(run, tmp_path) == sorted(_PRODUCT_TRACK_SURFACES)


def test_product_api_surface_observation_lane_excludes_the_test_tree(
    tmp_path: Path,
) -> None:
    """The baseline lane is probed alone: two consumers, two pins.

    ``ProjectMetrics.api_surface`` and the observation lane are fed from the
    same run but through different calls. A pin on one of them would pass on
    a fix that reached only that one, so the lane that becomes the baseline
    is measured on its own.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    lane = run.result.observation_bundle.structural.api_surface
    assert "api_surface" in run.result.observation_bundle.contract.enabled_lanes
    assert sorted({row.owner.file.path for row in lane}) == sorted(
        _PRODUCT_TRACK_SURFACES
    )


def test_product_api_track_follows_the_source_kind_owner(tmp_path: Path) -> None:
    """The track is the owner's verdict, not a copy of the owner's rule.

    Two files decide this. ``pkg/testing/tools.py`` is only production
    because the module registry proves ``pkg.testing`` is a shipped
    subpackage — a path rule alone reads ``testing`` as a test directory and
    drops it. ``pkg/test_helpers.py`` is only test-kind because the owner
    widens ``classify_source_kind`` with the pytest filename convention — a
    directory rule alone keeps it. Neither verdict can be reproduced without
    asking the owner, so a track that stopped delegating fails here.
    """

    _mixed_track_tree(tmp_path)
    shipped = tmp_path / "pkg" / "testing" / "tools.py"
    named_like_a_test = tmp_path / "pkg" / "test_helpers.py"
    registry = build_module_registry(root=tmp_path)
    assert is_product_api_module(
        str(shipped),
        scan_root=str(tmp_path),
        module_registry=registry,
    )
    assert not is_product_api_module(
        str(named_like_a_test),
        scan_root=str(tmp_path),
        module_registry=registry,
    )


def test_product_api_track_reads_repository_relative_paths(tmp_path: Path) -> None:
    """``scan_root`` is load-bearing, not decoration.

    A run carries absolute file paths and the owner classifies
    repository-relative ones. Drop the root and a repository that merely
    lives under a directory called ``test`` — a checkout in ``/tmp/test/…``,
    say — loses its whole public surface.
    """

    disguised_root = tmp_path / "testing" / "checkout"
    (disguised_root / "pkg").mkdir(parents=True)
    module = disguised_root / "pkg" / "mod.py"
    module.write_text("def run(value: int) -> int:\n    return value\n", "utf-8")
    assert is_product_api_module(str(module), scan_root=str(disguised_root))
    assert not is_product_api_module(str(module))


def test_product_api_modules_filters_without_reordering() -> None:
    """The producer's order survives the filter."""

    modules = tuple(
        ModuleApiSurface(module=name, filepath=path, symbols=())
        for name, path in (
            ("b", "pkg/b.py"),
            ("a", "tests/test_a.py"),
            ("c", "pkg/c.py"),
        )
    )
    assert [module.module for module in product_api_modules(modules)] == ["b", "c"]
