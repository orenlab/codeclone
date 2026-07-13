# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import ast
from pathlib import Path


def _module_name_from_path(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    return ".".join(parts)


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    parts = module_name.split(".")
    prefix_parts = parts[: -node.level]
    if node.module:
        return ".".join([*prefix_parts, node.module])
    return ".".join(prefix_parts)


def _iter_local_imports(module_name: str, source: str) -> list[str]:
    return [
        import_name
        for import_name, _line in _iter_import_edges(module_name, source)
        if import_name.startswith("codeclone")
    ]


def _iter_import_edges(module_name: str, source: str) -> list[tuple[str, int]]:
    tree = ast.parse(source)
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((_resolve_import(module_name, node), node.lineno))
    return imports
