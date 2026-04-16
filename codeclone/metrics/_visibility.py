# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..qualnames import QualnameCollector

__all__ = [
    "ModuleVisibility",
    "build_module_visibility",
    "is_public_method_name",
    "is_public_module_name",
]

_PUBLIC_METHOD_DUNDERS = frozenset(
    {"__call__", "__enter__", "__exit__", "__init__", "__iter__"}
)


@dataclass(frozen=True, slots=True)
class ModuleVisibility:
    module_name: str
    exported_names: frozenset[str]
    all_declared: tuple[str, ...] | None
    is_public_module: bool

    @property
    def strict_exports(self) -> bool:
        return self.all_declared is not None

    def exported_via(self, name: str) -> Literal["all", "name"] | None:
        if name not in self.exported_names:
            return None
        return "all" if self.strict_exports else "name"


def is_public_module_name(module_name: str) -> bool:
    return not any(part.startswith("_") for part in module_name.split(".") if part)


def is_public_method_name(name: str) -> bool:
    return not name.startswith("_") or name in _PUBLIC_METHOD_DUNDERS


def build_module_visibility(
    *,
    tree: ast.Module,
    module_name: str,
    collector: QualnameCollector,
    imported_names: Iterable[str],
    include_private_modules: bool = False,
) -> ModuleVisibility:
    declared_all = _declared_dunder_all(tree)
    public_module = include_private_modules or is_public_module_name(module_name)
    top_level_names = _top_level_declared_names(tree=tree, collector=collector)
    imported = frozenset(imported_names)
    if declared_all is not None:
        exported_names = frozenset(
            name for name in declared_all if name and name in top_level_names
        )
    elif public_module:
        exported_names = frozenset(
            name
            for name in top_level_names
            if not name.startswith("_") and name not in imported
        )
    else:
        exported_names = frozenset()
    return ModuleVisibility(
        module_name=module_name,
        exported_names=exported_names,
        all_declared=declared_all,
        is_public_module=public_module,
    )


def _declared_dunder_all(tree: ast.Module) -> tuple[str, ...] | None:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets: list[ast.Name] = []
        value: ast.AST | None
        if isinstance(node, ast.Assign):
            targets = [
                target for target in node.targets if isinstance(target, ast.Name)
            ]
            value = node.value
        else:
            targets = [node.target] if isinstance(node.target, ast.Name) else []
            value = node.value
        if not any(target.id == "__all__" for target in targets):
            continue
        rows = _literal_string_sequence(value)
        if rows is not None:
            return tuple(sorted(set(rows)))
    return None


def _literal_string_sequence(node: ast.AST | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        text = item.value.strip()
        if text:
            values.append(text)
    return tuple(values)


def _top_level_declared_names(
    *,
    tree: ast.Module,
    collector: QualnameCollector,
) -> frozenset[str]:
    names = {
        local_name
        for local_name, _node in collector.units
        if "." not in local_name and local_name
    }
    names.update(
        class_qualname
        for class_qualname, _node in collector.class_nodes
        if "." not in class_qualname and class_qualname
    )
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_assigned_names(target))
        elif isinstance(node, ast.AnnAssign):
            names.update(_assigned_names(node.target))
    return frozenset(name for name in names if name and name != "__all__")


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in node.elts:
            names.update(_assigned_names(item))
        return names
    return set()
