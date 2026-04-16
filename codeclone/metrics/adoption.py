# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ..models import ModuleDocstringCoverage, ModuleTypingCoverage
from ._visibility import (
    ModuleVisibility,
    build_module_visibility,
    is_public_method_name,
)

if TYPE_CHECKING:
    from ..qualnames import FunctionNode, QualnameCollector

__all__ = ["collect_module_adoption"]


def collect_module_adoption(
    *,
    tree: ast.Module,
    module_name: str,
    filepath: str,
    collector: QualnameCollector,
    imported_names: frozenset[str],
) -> tuple[ModuleTypingCoverage, ModuleDocstringCoverage]:
    visibility = build_module_visibility(
        tree=tree,
        module_name=module_name,
        collector=collector,
        imported_names=imported_names,
    )
    (
        public_symbol_total,
        public_symbol_documented,
        callable_count,
        params_total,
        params_annotated,
        returns_total,
        returns_annotated,
        any_annotation_count,
    ) = (0, 0, 0, 0, 0, 0, 0, 0)

    public_classes = {
        class_qualname
        for class_qualname, class_node in collector.class_nodes
        if "." not in class_qualname
        and visibility.exported_via(class_node.name) is not None
    }

    for local_name, node in collector.units:
        callable_count += 1
        param_rows = _function_param_rows(node=node, is_method="." in local_name)
        params_total += len(param_rows)
        params_annotated += sum(
            1 for _name, annotation in param_rows if annotation is not None
        )
        returns_total += 1
        returns_annotated += 1 if node.returns is not None else 0
        any_annotation_count += sum(
            1 for _name, annotation in param_rows if _is_any_annotation(annotation)
        )
        any_annotation_count += 1 if _is_any_annotation(node.returns) else 0

        if _is_public_docstring_target(
            local_name=local_name,
            node=node,
            visibility=visibility,
            public_classes=public_classes,
        ):
            public_symbol_total += 1
            if ast.get_docstring(node, clean=False) is not None:
                public_symbol_documented += 1

    for class_qualname, class_node in collector.class_nodes:
        if "." in class_qualname or visibility.exported_via(class_node.name) is None:
            continue
        public_symbol_total += 1
        if ast.get_docstring(class_node, clean=False) is not None:
            public_symbol_documented += 1

    return (
        ModuleTypingCoverage(
            module=module_name,
            filepath=filepath,
            callable_count=callable_count,
            params_total=params_total,
            params_annotated=params_annotated,
            returns_total=returns_total,
            returns_annotated=returns_annotated,
            any_annotation_count=any_annotation_count,
        ),
        ModuleDocstringCoverage(
            module=module_name,
            filepath=filepath,
            public_symbol_total=public_symbol_total,
            public_symbol_documented=public_symbol_documented,
        ),
    )


def _function_param_rows(
    *,
    node: FunctionNode,
    is_method: bool,
) -> tuple[tuple[str, ast.AST | None], ...]:
    args = node.args
    pos_args = [*args.posonlyargs, *args.args]
    rows: list[tuple[str, ast.AST | None]] = []

    for index, arg in enumerate(pos_args):
        if is_method and index == 0 and arg.arg in {"self", "cls"}:
            continue
        rows.append((arg.arg, arg.annotation))
    if args.vararg is not None:
        rows.append((args.vararg.arg, args.vararg.annotation))
    rows.extend((arg.arg, arg.annotation) for arg in args.kwonlyargs)
    if args.kwarg is not None:
        rows.append((args.kwarg.arg, args.kwarg.annotation))
    return tuple(rows)


def _is_public_docstring_target(
    *,
    local_name: str,
    node: FunctionNode,
    visibility: ModuleVisibility,
    public_classes: set[str],
) -> bool:
    if "." not in local_name:
        return visibility.exported_via(node.name) is not None
    class_name, _, method_name = local_name.partition(".")
    return class_name in public_classes and is_public_method_name(method_name)


def _is_any_annotation(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "Any"
    if isinstance(node, ast.Attribute):
        return _attribute_name(node) in {"typing.Any", "typing_extensions.Any"}
    if isinstance(node, ast.Subscript):
        return _is_any_annotation(node.value) or _is_any_annotation(node.slice)
    if isinstance(node, ast.Tuple):
        return any(_is_any_annotation(item) for item in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_any_annotation(node.left) or _is_any_annotation(node.right)
    return False


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None
