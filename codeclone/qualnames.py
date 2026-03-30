# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

__all__ = ["FunctionNode", "QualnameCollector"]

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class QualnameCollector(ast.NodeVisitor):
    __slots__ = (
        "class_count",
        "class_nodes",
        "funcs",
        "function_count",
        "method_count",
        "stack",
        "units",
    )

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.units: list[tuple[str, FunctionNode]] = []
        self.class_nodes: list[tuple[str, ast.ClassDef]] = []
        self.funcs: dict[str, FunctionNode] = {}
        self.class_count = 0
        self.function_count = 0
        self.method_count = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_count += 1
        class_qualname = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.class_nodes.append((class_qualname, node))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _register_function(self, node: FunctionNode) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
        if self.stack:
            self.method_count += 1
        else:
            self.function_count += 1
        self.units.append((name, node))
        self.funcs[name] = node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._register_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._register_function(node)
