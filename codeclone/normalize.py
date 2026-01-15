from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizationConfig:
    ignore_docstrings: bool = True
    ignore_type_annotations: bool = True
    normalize_attributes: bool = True  # obj.foo -> obj._ATTR_
    normalize_constants: bool = True  # 123/"x"/None -> _CONST_
    normalize_names: bool = True  # x,y,z -> _VAR_


class AstNormalizer(ast.NodeTransformer):
    def __init__(self, cfg: NormalizationConfig):
        self.cfg = cfg
        super().__init__()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self._visit_func(node)

    def _visit_func(self, node):
        # Drop docstring (first Expr(Constant(str)))
        if self.cfg.ignore_docstrings and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                if isinstance(first.value.value, str):
                    node.body = node.body[1:]

        if self.cfg.ignore_type_annotations:
            # Remove annotations in args + returns
            if hasattr(node, "returns"):
                node.returns = None
            args = node.args
            for a in getattr(args, "posonlyargs", []):
                a.annotation = None
            for a in getattr(args, "args", []):
                a.annotation = None
            for a in getattr(args, "kwonlyargs", []):
                a.annotation = None
            if getattr(args, "vararg", None):
                args.vararg.annotation = None
            if getattr(args, "kwarg", None):
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

    def visit_Attribute(self, node: ast.Attribute):
        node = self.generic_visit(node)
        if self.cfg.normalize_attributes:
            node.attr = "_ATTR_"
        return node

    def visit_Constant(self, node: ast.Constant):
        if self.cfg.normalize_constants:
            # Preserve booleans? up to you; default: normalize everything
            node.value = "_CONST_"
        return node


def normalized_ast_dump(func_node: ast.AST, cfg: NormalizationConfig) -> str:
    """
    Returns stable string representation of normalized AST.
    """
    normalizer = AstNormalizer(cfg)
    new_node = ast.fix_missing_locations(normalizer.visit(ast.copy_location(func_node, func_node)))
    # include_attributes=False => more stable; annotate_fields=True => default
    return ast.dump(new_node, annotate_fields=True, include_attributes=False)
