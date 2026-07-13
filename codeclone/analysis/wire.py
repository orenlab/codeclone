# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Versioned, read-only normalized AST wire emission."""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Sequence
from typing import Final, TypeGuard

from ..contracts import WIRE_VERSION as WIRE_VERSION
from ..meta_markers import CFG_META_PREFIX
from .normalizer import NormalizationConfig


class WireUnsupportedNode(Exception):
    """A node type or field is outside the canonical wire whitelist."""


_EXCLUDED_FIELDS: Final = frozenset(
    {
        "col_offset",
        "ctx",
        "end_col_offset",
        "end_lineno",
        "kind",
        "lineno",
        "type_comment",
        "type_params",
    }
)

# Names are used here so importing this module remains valid on Python 3.10.
# Every entry is still an explicit, reviewed field contract; optional grammar
# nodes are registered only when the running interpreter exposes them.
_WIRE_FIELD_SPECS: Final[dict[str, tuple[str, ...]]] = {
    "Module": ("body", "type_ignores"),
    "Interactive": ("body",),
    "Expression": ("body",),
    "FunctionType": ("argtypes", "returns"),
    "FunctionDef": ("name", "args", "body", "decorator_list", "returns"),
    "AsyncFunctionDef": (
        "name",
        "args",
        "body",
        "decorator_list",
        "returns",
    ),
    "ClassDef": ("name", "bases", "keywords", "body", "decorator_list"),
    "Return": ("value",),
    "Delete": ("targets",),
    "Assign": ("targets", "value"),
    "AugAssign": ("target", "op", "value"),
    "AnnAssign": ("target", "annotation", "value", "simple"),
    "For": ("target", "iter", "body", "orelse"),
    "AsyncFor": ("target", "iter", "body", "orelse"),
    "While": ("test", "body", "orelse"),
    "If": ("test", "body", "orelse"),
    "With": ("items", "body"),
    "AsyncWith": ("items", "body"),
    "Match": ("subject", "cases"),
    "Raise": ("exc", "cause"),
    "Try": ("body", "handlers", "orelse", "finalbody"),
    "TryStar": ("body", "handlers", "orelse", "finalbody"),
    "Assert": ("test", "msg"),
    "Import": ("names",),
    "ImportFrom": ("module", "names", "level"),
    "Global": ("names",),
    "Nonlocal": ("names",),
    "Expr": ("value",),
    "Pass": (),
    "Break": (),
    "Continue": (),
    "TypeAlias": ("name", "value"),
    "BoolOp": ("op", "values"),
    "NamedExpr": ("target", "value"),
    "BinOp": ("left", "op", "right"),
    "UnaryOp": ("op", "operand"),
    "Lambda": ("args", "body"),
    "IfExp": ("test", "body", "orelse"),
    "Dict": ("keys", "values"),
    "Set": ("elts",),
    "ListComp": ("elt", "generators"),
    "SetComp": ("elt", "generators"),
    "DictComp": ("key", "value", "generators"),
    "GeneratorExp": ("elt", "generators"),
    "Await": ("value",),
    "Yield": ("value",),
    "YieldFrom": ("value",),
    "Compare": ("left", "ops", "comparators"),
    "Call": ("func", "args", "keywords"),
    "FormattedValue": ("value", "conversion", "format_spec"),
    "JoinedStr": ("values",),
    "TemplateStr": ("values",),
    "Interpolation": ("value", "str", "conversion", "format_spec"),
    "Constant": ("value",),
    "Attribute": ("value", "attr"),
    "Subscript": ("value", "slice"),
    "Starred": ("value",),
    "Name": ("id",),
    "List": ("elts",),
    "Tuple": ("elts",),
    "Slice": ("lower", "upper", "step"),
    "comprehension": ("target", "iter", "ifs", "is_async"),
    "ExceptHandler": ("type", "name", "body"),
    "arguments": (
        "posonlyargs",
        "args",
        "vararg",
        "kwonlyargs",
        "kw_defaults",
        "kwarg",
        "defaults",
    ),
    "arg": ("arg", "annotation"),
    "keyword": ("arg", "value"),
    "alias": ("name", "asname"),
    "withitem": ("context_expr", "optional_vars"),
    "match_case": ("pattern", "guard", "body"),
    "MatchValue": ("value",),
    "MatchSingleton": ("value",),
    "MatchSequence": ("patterns",),
    "MatchMapping": ("keys", "patterns", "rest"),
    "MatchClass": ("cls", "patterns", "kwd_attrs", "kwd_patterns"),
    "MatchStar": ("name",),
    "MatchAs": ("pattern", "name"),
    "MatchOr": ("patterns",),
    "TypeIgnore": ("tag",),
    "TypeVar": ("name", "bound", "default_value"),
    "ParamSpec": ("name", "default_value"),
    "TypeVarTuple": ("name", "default_value"),
    "And": (),
    "Or": (),
    "Add": (),
    "Sub": (),
    "Mult": (),
    "MatMult": (),
    "Div": (),
    "Mod": (),
    "Pow": (),
    "LShift": (),
    "RShift": (),
    "BitOr": (),
    "BitXor": (),
    "BitAnd": (),
    "FloorDiv": (),
    "Invert": (),
    "Not": (),
    "UAdd": (),
    "USub": (),
    "Eq": (),
    "NotEq": (),
    "Lt": (),
    "LtE": (),
    "Gt": (),
    "GtE": (),
    "Is": (),
    "IsNot": (),
    "In": (),
    "NotIn": (),
    "Load": (),
    "Store": (),
    "Del": (),
}


def _is_ast_type(value: object) -> TypeGuard[type[ast.AST]]:
    return isinstance(value, type) and issubclass(value, ast.AST)


def _build_wire_fields() -> dict[type[ast.AST], tuple[str, ...]]:
    fields: dict[type[ast.AST], tuple[str, ...]] = {}
    namespace = vars(ast)
    for node_name, node_fields in _WIRE_FIELD_SPECS.items():
        node_type = namespace.get(node_name)
        if _is_ast_type(node_type):
            fields[node_type] = node_fields
    return fields


_WIRE_FIELDS: Final[dict[type[ast.AST], tuple[str, ...]]] = _build_wire_fields()

_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_STRUCTURAL_INT_FIELDS: Final = frozenset({"conversion", "is_async", "level", "simple"})


def emit_wire(node: ast.AST, cfg: NormalizationConfig) -> str:
    """Return the canonical normalized wire without mutating ``node``."""

    return _emit_node(node, cfg, preserve_symbol=False)


def emit_wire_seq(nodes: Sequence[ast.AST], cfg: NormalizationConfig) -> str:
    """Return canonical wires joined with the legacy statement separator."""

    return ";".join(emit_wire(node, cfg) for node in nodes)


def _emit_node(
    node: ast.AST,
    cfg: NormalizationConfig,
    *,
    preserve_symbol: bool,
) -> str:
    node_type = type(node)
    fields = _WIRE_FIELDS.get(node_type)
    if fields is None:
        raise WireUnsupportedNode(f"unsupported AST node: {node_type.__name__}")
    _check_fields(node, fields)

    if isinstance(node, ast.AugAssign):
        return _emit_aug_assign(node, cfg)
    if isinstance(node, ast.UnaryOp):
        rewritten = _emit_negated_compare(node, cfg)
        if rewritten is not None:
            return rewritten
    if isinstance(node, ast.BinOp):
        return _emit_bin_op(node, cfg)
    if isinstance(node, ast.Name):
        return _emit_name(node, cfg, preserve_symbol=preserve_symbol)
    if isinstance(node, ast.Attribute):
        return _emit_attribute(node, cfg, preserve_symbol=preserve_symbol)

    parts: list[str] = [node_type.__name__, "("]
    for index, field in enumerate(fields):
        if index:
            parts.append(",")
        parts.extend((field, "=", _emit_field(node, field, cfg)))
    parts.append(")")
    return "".join(parts)


def _check_fields(node: ast.AST, fields: tuple[str, ...]) -> None:
    allowed = frozenset(fields) | _EXCLUDED_FIELDS
    unknown = tuple(field for field in node._fields if field not in allowed)
    if unknown:
        joined = ",".join(unknown)
        raise WireUnsupportedNode(
            f"unsupported fields on {type(node).__name__}: {joined}"
        )


def _emit_field(node: ast.AST, field: str, cfg: NormalizationConfig) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _emit_function_field(node, field, cfg)
    if isinstance(node, ast.arg):
        return _emit_arg_field(node, field, cfg)
    if isinstance(node, ast.Constant):
        return _emit_constant(node.value, cfg)
    if isinstance(node, ast.Call):
        return _emit_call_field(node, field, cfg)
    if isinstance(node, ast.MatchClass):
        return _emit_match_class_field(node, field, cfg)
    if isinstance(node, ast.MatchValue):
        return _emit_preserved_expression(node.value, cfg)
    if isinstance(node, ast.ExceptHandler):
        return _emit_except_handler_field(node, field, cfg)
    return _emit_capture_or_generic_field(node, field, cfg)


def _emit_function_field(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    field: str,
    cfg: NormalizationConfig,
) -> str:
    if field == "body":
        body = node.body
        if cfg.ignore_docstrings and body and _is_docstring(body[0]):
            body = body[1:]
        return _emit_list(body, cfg)
    if field == "returns" and cfg.ignore_type_annotations:
        return "None"
    return _emit_generic_field(node, field, cfg)


def _emit_arg_field(node: ast.arg, field: str, cfg: NormalizationConfig) -> str:
    if field == "annotation" and cfg.ignore_type_annotations:
        return "None"
    return _emit_generic_field(node, field, cfg)


def _emit_call_field(node: ast.Call, field: str, cfg: NormalizationConfig) -> str:
    if field == "func":
        return _emit_preserved_expression(node.func, cfg)
    return _emit_generic_field(node, field, cfg)


def _emit_match_class_field(
    node: ast.MatchClass, field: str, cfg: NormalizationConfig
) -> str:
    if field == "cls":
        return _emit_node(node.cls, cfg, preserve_symbol=True)
    return _emit_generic_field(node, field, cfg)


def _emit_except_handler_field(
    node: ast.ExceptHandler, field: str, cfg: NormalizationConfig
) -> str:
    if field != "type":
        return _emit_generic_field(node, field, cfg)
    if node.type is None:
        return "None"
    return _emit_preserved_expression(node.type, cfg)


def _emit_preserved_expression(node: ast.expr, cfg: NormalizationConfig) -> str:
    return _emit_node(
        node,
        cfg,
        preserve_symbol=isinstance(node, (ast.Name, ast.Attribute)),
    )


def _emit_capture_or_generic_field(
    node: ast.AST, field: str, cfg: NormalizationConfig
) -> str:
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and field == "name":
        return _emit_capture_name(vars(node).get(field), cfg)
    if isinstance(node, ast.MatchMapping) and field == "rest":
        return _emit_capture_name(node.rest, cfg)
    if type(node).__name__ == "Interpolation" and field == "str":
        return "_CONST_"
    if isinstance(node, ast.TypeIgnore) and field == "tag":
        return "_CONST_"
    return _emit_generic_field(node, field, cfg)


def _emit_generic_field(node: ast.AST, field: str, cfg: NormalizationConfig) -> str:
    field_value = vars(node).get(field)
    return _emit_value(field_value, cfg, field=field)


def _emit_value(value: object, cfg: NormalizationConfig, *, field: str) -> str:
    if isinstance(value, ast.AST):
        return _emit_node(value, cfg, preserve_symbol=False)
    if isinstance(value, list):
        return _emit_list(value, cfg)
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, int) and field in _STRUCTURAL_INT_FIELDS:
        return str(value)
    if isinstance(value, str):
        return _emit_identifier(value)
    raise WireUnsupportedNode(
        f"unsupported value for field {field}: {type(value).__name__}"
    )


def _emit_list(values: Sequence[object], cfg: NormalizationConfig) -> str:
    items = ",".join(_emit_value(value, cfg, field="list") for value in values)
    return "[" + items + "]"


def _emit_identifier(value: str) -> str:
    if value == "*":
        return "_STAR_"
    if value.startswith(CFG_META_PREFIX):
        return value
    if all(_IDENTIFIER.fullmatch(part) for part in value.split(".")):
        return value
    raise WireUnsupportedNode("unsafe identifier in AST field")


def _emit_capture_name(value: object, cfg: NormalizationConfig) -> str:
    if value is None:
        return "None"
    if not isinstance(value, str):
        raise WireUnsupportedNode("capture name is not a string")
    if cfg.normalize_names:
        return "_VAR_"
    return _emit_identifier(value)


def _emit_constant(value: object, cfg: NormalizationConfig) -> str:
    if cfg.normalize_constants:
        return "_CONST_"
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (str, bytes, float, complex)) or value is Ellipsis:
        payload = f"{type(value).__name__}:{value!r}".encode()
        return "CONST_" + hashlib.sha256(payload).hexdigest()
    raise WireUnsupportedNode(f"unsupported constant value: {type(value).__name__}")


def _emit_name(
    node: ast.Name,
    cfg: NormalizationConfig,
    *,
    preserve_symbol: bool,
) -> str:
    if (
        preserve_symbol
        or not cfg.normalize_names
        or node.id.startswith(CFG_META_PREFIX)
    ):
        identifier = _emit_identifier(node.id)
    else:
        identifier = "_VAR_"
    return f"Name(id={identifier})"


def _emit_attribute(
    node: ast.Attribute,
    cfg: NormalizationConfig,
    *,
    preserve_symbol: bool,
) -> str:
    preserve_value = preserve_symbol and isinstance(
        node.value, (ast.Name, ast.Attribute)
    )
    value = _emit_node(node.value, cfg, preserve_symbol=preserve_value)
    if preserve_symbol or not cfg.normalize_attributes:
        attribute = _emit_identifier(node.attr)
    else:
        attribute = "_ATTR_"
    return f"Attribute(value={value},attr={attribute})"


def _emit_aug_assign(node: ast.AugAssign, cfg: NormalizationConfig) -> str:
    target = _emit_node(node.target, cfg, preserve_symbol=False)
    operation = _emit_node(node.op, cfg, preserve_symbol=False)
    value = _emit_node(node.value, cfg, preserve_symbol=False)
    return (
        "Assign(targets=["
        + target
        + "],value=BinOp(left="
        + target
        + ",op="
        + operation
        + ",right="
        + value
        + "))"
    )


def _emit_negated_compare(node: ast.UnaryOp, cfg: NormalizationConfig) -> str | None:
    if not isinstance(node.op, ast.Not) or not isinstance(node.operand, ast.Compare):
        return None
    operand = node.operand
    if len(operand.ops) != 1 or len(operand.comparators) != 1:
        return None
    operation = operand.ops[0]
    if isinstance(operation, ast.In):
        operation_wire = "NotIn()"
    elif isinstance(operation, ast.Is):
        operation_wire = "IsNot()"
    else:
        return None
    left = _emit_node(operand.left, cfg, preserve_symbol=False)
    comparator = _emit_node(operand.comparators[0], cfg, preserve_symbol=False)
    return (
        "Compare(left="
        + left
        + ",ops=["
        + operation_wire
        + "],comparators=["
        + comparator
        + "])"
    )


def _emit_bin_op(node: ast.BinOp, cfg: NormalizationConfig) -> str:
    left = _emit_node(node.left, cfg, preserve_symbol=False)
    right = _emit_node(node.right, cfg, preserve_symbol=False)
    if (
        isinstance(node.op, (ast.Add, ast.Mult, ast.BitOr, ast.BitAnd, ast.BitXor))
        and _is_proven_commutative_operand(node.left, node.op)
        and _is_proven_commutative_operand(node.right, node.op)
        and right < left
    ):
        left, right = right, left
    operation = _emit_node(node.op, cfg, preserve_symbol=False)
    return f"BinOp(left={left},op={operation},right={right})"


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


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


__all__ = ["WIRE_VERSION", "WireUnsupportedNode", "emit_wire", "emit_wire_seq"]
