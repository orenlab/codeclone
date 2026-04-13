# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

from codeclone.metrics import _visibility as visibility_mod
from codeclone.metrics import adoption as adoption_mod
from codeclone.metrics._visibility import build_module_visibility
from codeclone.metrics.adoption import collect_module_adoption
from codeclone.qualnames import QualnameCollector
from tests._ast_metrics_helpers import tree_collector_and_imports


def test_build_module_visibility_supports_strict_dunder_all_for_private_modules() -> (
    None
):
    tree, collector, import_names = tree_collector_and_imports(
        """
__all__ = ["public_fn", "PublicClass"]

def public_fn():
    return 1

def _private_fn():
    return 2

class PublicClass:
    pass
""",
        module_name="pkg._internal",
    )
    visibility = build_module_visibility(
        tree=tree,
        module_name="pkg._internal",
        collector=collector,
        imported_names=import_names,
    )

    assert visibility.is_public_module is False
    assert visibility.strict_exports is True
    assert visibility.exported_names == frozenset({"PublicClass", "public_fn"})
    assert visibility.exported_via("public_fn") == "all"
    assert visibility.exported_via("_private_fn") is None


def test_collect_module_adoption_counts_annotations_docstrings_and_any() -> None:
    tree, collector, import_names = tree_collector_and_imports(
        """
from typing import Any

__all__ = ["public", "Public"]

def public(a: int, b) -> Any:
    \"\"\"Public function.\"\"\"
    return b

def _private(hidden):
    return hidden

class Public:
    \"\"\"Public class.\"\"\"

    def method(self, item: Any) -> None:
        \"\"\"Public method.\"\"\"
        return None

    def _hidden(self, value: int) -> None:
        return None
""",
        module_name="pkg.mod",
    )

    typing_coverage, docstring_coverage = collect_module_adoption(
        tree=tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=collector,
        imported_names=import_names,
    )

    assert (
        typing_coverage.module,
        typing_coverage.filepath,
        typing_coverage.callable_count,
        typing_coverage.params_total,
        typing_coverage.params_annotated,
        typing_coverage.returns_total,
        typing_coverage.returns_annotated,
        typing_coverage.any_annotation_count,
    ) == ("pkg.mod", "pkg/mod.py", 4, 5, 3, 4, 3, 2)

    assert (
        docstring_coverage.module,
        docstring_coverage.filepath,
        docstring_coverage.public_symbol_total,
        docstring_coverage.public_symbol_documented,
    ) == ("pkg.mod", "pkg/mod.py", 3, 3)


def test_visibility_helpers_cover_private_modules_and_declared_all_edges() -> None:
    tree, collector, import_names = tree_collector_and_imports(
        """
items: list[str] = []
_private = 1
""",
        module_name="pkg._internal",
    )
    visibility = build_module_visibility(
        tree=tree,
        module_name="pkg._internal",
        collector=collector,
        imported_names=import_names,
    )
    assert visibility.exported_names == frozenset()

    strict_tree = ast.parse(
        """
__all__: list[str] = ["Public", "CONST", ""]
(foo, [bar, baz]) = (1, [2, 3])
CONST: int = 1

class Public:
    pass
"""
    )
    strict_collector = QualnameCollector()
    strict_collector.visit(strict_tree)
    declared_all = visibility_mod._declared_dunder_all(strict_tree)
    top_level_names = visibility_mod._top_level_declared_names(
        tree=strict_tree,
        collector=strict_collector,
    )

    assert declared_all == ("CONST", "Public")
    assert {"foo", "bar", "baz", "CONST", "Public"}.issubset(top_level_names)
    assert visibility_mod._literal_string_sequence(ast.Constant(value="x")) is None
    assert (
        visibility_mod._literal_string_sequence(ast.List(elts=[ast.Constant(value=1)]))
        is None
    )
    assign = ast.parse("(left, [right, tail]) = values").body[0]
    assert isinstance(assign, ast.Assign)
    assert visibility_mod._assigned_names(assign.targets[0]) == {
        "left",
        "right",
        "tail",
    }


def test_adoption_helper_rows_and_any_helpers_cover_method_and_variants() -> None:
    function = ast.parse(
        """
def method(
    self,
    a: int,
    /,
    b,
    *args: typing.Any,
    c: int,
    **kwargs: typing.Any,
) -> typing.Any | None:
    return None
"""
    ).body[0]
    assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))

    rows = adoption_mod._function_param_rows(node=function, is_method=True)
    assert [name for name, _annotation in rows] == ["a", "b", "args", "c", "kwargs"]

    typing_any = ast.parse("typing.Any", mode="eval").body
    union_any = ast.parse("typing.Any | int", mode="eval").body
    assert adoption_mod._is_any_annotation(typing_any) is True
    assert adoption_mod._is_any_annotation(union_any) is True
    assert adoption_mod._attribute_name(typing_any) == "typing.Any"
    assert adoption_mod._attribute_name(ast.Constant(value=1)) is None
