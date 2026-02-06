"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
import copy
from ast import AST
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from .meta_markers import CFG_META_PREFIX


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    ignore_docstrings: bool = True
    ignore_type_annotations: bool = True
    normalize_attributes: bool = True
    normalize_constants: bool = True
    normalize_names: bool = True


class AstNormalizer(ast.NodeTransformer):
    __slots__ = ("cfg",)

    def __init__(self, cfg: NormalizationConfig):
        super().__init__()
        self.cfg = cfg

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
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

    def visit_arg(self, node: ast.arg) -> ast.arg:
        if self.cfg.ignore_type_annotations:
            node.annotation = None
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        # Call targets are handled in visit_Call to avoid erasing callee symbols.
        if self.cfg.normalize_names and not _is_semantic_marker_name(node.id):
            node.id = "_VAR_"
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        new_node = self.generic_visit(node)
        assert isinstance(new_node, ast.Attribute)
        if self.cfg.normalize_attributes:
            new_node.attr = "_ATTR_"
        return new_node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if self.cfg.normalize_constants:
            node.value = "_CONST_"
        return node

    def visit_Call(self, node: ast.Call) -> ast.Call:
        node.func = self._visit_call_target(node.func)
        node.args = [cast(ast.expr, self.visit(arg)) for arg in node.args]
        for kw in node.keywords:
            kw.value = cast(ast.expr, self.visit(kw.value))
        return node

    def _visit_call_target(self, node: ast.expr) -> ast.expr:
        # Keep symbolic call targets intact to avoid conflating different APIs.
        if isinstance(node, ast.Name):
            return node
        if isinstance(node, ast.Attribute):
            value = node.value
            if isinstance(value, (ast.Name, ast.Attribute)):
                node.value = self._visit_call_target(value)
            else:
                node.value = cast(ast.expr, self.visit(value))
            return node
        return cast(ast.expr, self.visit(node))

    def visit_AugAssign(self, node: ast.AugAssign) -> AST:
        # Normalize x += 1 to x = x + 1
        # This allows detecting clones where one uses += and another uses = +
        # We transform AugAssign(target, op, value) to Assign([target],
        # BinOp(target, op, value))

        # Deepcopy target to avoid reuse issues in the AST
        target_load = copy.deepcopy(node.target)
        # Ensure context is Load() for the right-hand side usage
        if hasattr(target_load, "ctx"):
            target_load.ctx = ast.Load()

        new_node = ast.Assign(
            targets=[node.target],
            value=ast.BinOp(left=target_load, op=node.op, right=node.value),
            lineno=node.lineno,
            col_offset=node.col_offset,
            end_lineno=getattr(node, "end_lineno", None),
            end_col_offset=getattr(node, "end_col_offset", None),
        )
        return self.generic_visit(new_node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        new_node = self.generic_visit(node)
        assert isinstance(new_node, ast.UnaryOp)

        if isinstance(new_node.op, ast.Not):
            operand = new_node.operand
            if (
                isinstance(operand, ast.Compare)
                and len(operand.ops) == 1
                and len(operand.comparators) == 1
            ):
                op = operand.ops[0]
                if isinstance(op, ast.In):
                    cmp = ast.Compare(
                        left=operand.left,
                        ops=[ast.NotIn()],
                        comparators=operand.comparators,
                    )
                    return ast.copy_location(cmp, new_node)
                if isinstance(op, ast.Is):
                    cmp = ast.Compare(
                        left=operand.left,
                        ops=[ast.IsNot()],
                        comparators=operand.comparators,
                    )
                    return ast.copy_location(cmp, new_node)
        return new_node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        new_node = self.generic_visit(node)
        assert isinstance(new_node, ast.BinOp)

        if not isinstance(
            new_node.op, (ast.Add, ast.Mult, ast.BitOr, ast.BitAnd, ast.BitXor)
        ):
            return new_node

        if not (
            _is_proven_commutative_operand(new_node.left, new_node.op)
            and _is_proven_commutative_operand(new_node.right, new_node.op)
        ):
            return new_node

        left_key = _expr_sort_key(new_node.left)
        right_key = _expr_sort_key(new_node.right)
        if right_key < left_key:
            new_node.left, new_node.right = new_node.right, new_node.left
        return new_node


def _expr_sort_key(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _is_semantic_marker_name(name: str) -> bool:
    return name.startswith(CFG_META_PREFIX)


def _is_proven_commutative_operand(node: ast.AST, op: ast.operator) -> bool:
    if isinstance(node, ast.Constant):
        return _is_proven_commutative_constant(node.value, op)
    if isinstance(node, ast.BinOp) and type(node.op) is type(op):
        return _is_proven_commutative_operand(
            node.left, op
        ) and _is_proven_commutative_operand(node.right, op)
    return False


def _is_proven_commutative_constant(value: object, op: ast.operator) -> bool:
    if isinstance(op, (ast.BitOr, ast.BitAnd, ast.BitXor)):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(op, (ast.Add, ast.Mult)):
        return isinstance(value, (int, float, complex)) and not isinstance(value, bool)
    return False


def normalized_ast_dump(func_node: ast.AST, cfg: NormalizationConfig) -> str:
    """
    Dump the normalized AST.
    WARNING: This modifies the AST in-place for performance.
    """
    normalizer = AstNormalizer(cfg)
    new_node = ast.fix_missing_locations(normalizer.visit(func_node))
    return ast.dump(new_node, annotate_fields=True, include_attributes=False)


def normalized_ast_dump_from_list(
    nodes: Sequence[ast.AST], cfg: NormalizationConfig
) -> str:
    """
    Dump a list of AST nodes after normalization.
    WARNING: This modifies the AST nodes in-place for performance.
    """
    normalizer = AstNormalizer(cfg)
    dumps: list[str] = []

    for node in nodes:
        new_node = ast.fix_missing_locations(normalizer.visit(node))
        dumps.append(ast.dump(new_node, annotate_fields=True, include_attributes=False))

    return ";".join(dumps)
