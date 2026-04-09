# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import Literal, cast

from codeclone import extractor
from codeclone.metrics import api_surface as api_surface_mod
from codeclone.metrics._visibility import ModuleVisibility
from codeclone.metrics.api_surface import (
    collect_module_api_surface,
    compare_api_surfaces,
)
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    ModuleApiSurface,
    PublicSymbol,
)
from codeclone.qualnames import QualnameCollector


def _tree_collector_and_imports(
    source: str,
    *,
    module_name: str,
) -> tuple[ast.Module, QualnameCollector, frozenset[str]]:
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name=module_name,
        collector=collector,
        collect_referenced_names=True,
    )
    return tree, collector, walk.import_names


def test_collect_module_api_surface_skips_self_and_collects_public_symbols() -> None:
    tree, collector, import_names = _tree_collector_and_imports(
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
    private_tree, private_collector, private_imports = _tree_collector_and_imports(
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

    empty_tree, empty_collector, empty_imports = _tree_collector_and_imports(
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
    outer_class = ast.parse(
        """
class Outer:
    class Inner:
        pass
"""
    ).body[0]
    assert isinstance(outer_class, ast.ClassDef)
    nested_class = outer_class.body[0]
    assert isinstance(nested_class, ast.ClassDef)
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
