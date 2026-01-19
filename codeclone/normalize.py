"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizationConfig:
    ignore_docstrings: bool = True
    ignore_type_annotations: bool = True
    normalize_attributes: bool = True
    normalize_constants: bool = True
    normalize_names: bool = True


class AstNormalizer(ast.NodeTransformer):
    def __init__(self, cfg: NormalizationConfig):
        super().__init__()
        self.cfg = cfg

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # Drop docstring
        if self.cfg.ignore_docstrings and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:]

        if self.cfg.ignore_type_annotations:
            node.returns = None
            args = node.args

            for a in getattr(args, "posonlyargs", []):
                a.annotation = None
            for a in args.args:
                a.annotation = None
            for a in args.kwonlyargs:
                a.annotation = None
            if args.vararg:
                args.vararg.annotation = None
            if args.kwarg:
                args.kwarg.annotation = None

        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg):
        if self.cfg.ignore_type_annotations:
            node.annotation = None
        return node

    def visit_Name(self, node: ast.Name):
        if self.cfg.normalize_names:
            node.id = "_VAR_"
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        new_node = self.generic_visit(node)
        assert isinstance(new_node, ast.Attribute)
        if self.cfg.normalize_attributes:
            new_node.attr = "_ATTR_"
        return new_node

    def visit_Constant(self, node: ast.Constant):
        if self.cfg.normalize_constants:
            node.value = "_CONST_"
        return node


def normalized_ast_dump(func_node: ast.AST, cfg: NormalizationConfig) -> str:
    normalizer = AstNormalizer(cfg)
    new_node = ast.fix_missing_locations(
        normalizer.visit(ast.copy_location(func_node, func_node))
    )
    return ast.dump(new_node, annotate_fields=True, include_attributes=False)


def normalized_ast_dump_from_list(
    nodes: Sequence[ast.AST], cfg: NormalizationConfig
) -> str:
    normalizer = AstNormalizer(cfg)
    dumps: list[str] = []

    for node in nodes:
        new_node = ast.fix_missing_locations(
            normalizer.visit(ast.copy_location(node, node))
        )
        dumps.append(ast.dump(new_node, annotate_fields=True, include_attributes=False))

    return ";".join(dumps)
