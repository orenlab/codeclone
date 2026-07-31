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
from .binding import BindingContext
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
_COMPREHENSION_TYPES: Final = (
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def emit_wire(
    node: ast.AST,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    """Return the canonical normalized wire without mutating ``node``.

    ``bindings`` is the lexical scope the node is written in. It is required
    rather than defaulted: the wire now states what each symbol denotes, and a
    caller that silently fell back to "no bindings" would publish names as
    unknown globals without anyone noticing.
    """

    return _emit_node(node, cfg, bindings)


def emit_wire_seq(
    nodes: Sequence[ast.AST],
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    """Return canonical wires joined with the legacy statement separator."""

    return ";".join(emit_wire(node, cfg, bindings) for node in nodes)


def _emit_node(
    node: ast.AST,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    node_type = type(node)
    fields = _WIRE_FIELDS.get(node_type)
    if fields is None:
        raise WireUnsupportedNode(f"unsupported AST node: {node_type.__name__}")
    _check_fields(node, fields)

    if isinstance(node, ast.AugAssign):
        return _emit_aug_assign(node, cfg, bindings)
    if isinstance(node, ast.UnaryOp):
        rewritten = _emit_negated_compare(node, cfg, bindings)
        if rewritten is not None:
            return rewritten
    if isinstance(node, ast.BinOp):
        return _emit_bin_op(node, cfg, bindings)
    if isinstance(node, ast.Name):
        return _emit_name(node, cfg, bindings)
    if isinstance(node, ast.Attribute):
        return _emit_attribute(node, cfg, bindings)

    parts: list[str] = [node_type.__name__, "("]
    for index, field in enumerate(fields):
        if index:
            parts.append(",")
        parts.extend((field, "=", _emit_field(node, field, cfg, bindings)))
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


def _emit_field(
    node: ast.AST,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _emit_function_field(node, field, cfg, bindings)
    if isinstance(node, ast.Lambda):
        return _emit_lambda_field(node, field, cfg, bindings)
    if isinstance(node, ast.ClassDef):
        return _emit_class_field(node, field, cfg, bindings)
    if isinstance(node, _COMPREHENSION_TYPES):
        return _emit_comprehension_field(node, field, cfg, bindings)
    if isinstance(node, ast.arg):
        return _emit_arg_field(node, field, cfg, bindings)
    if isinstance(node, ast.Constant):
        return _emit_constant(node.value, cfg)
    return _emit_capture_or_generic_field(node, field, cfg, bindings)


def _emit_function_field(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if field == "body":
        body = node.body
        if cfg.ignore_docstrings and body and _is_docstring(body[0]):
            body = body[1:]
        return _emit_list(body, cfg, bindings.enter(node))
    if field == "returns" and cfg.ignore_type_annotations:
        return "None"
    # Decorators, defaults and annotations are evaluated where the definition
    # is written, so they stay in the enclosing scope.
    return _emit_generic_field(node, field, cfg, bindings)


def _emit_lambda_field(
    node: ast.Lambda,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if field == "body":
        return _emit_node(node.body, cfg, bindings.enter(node))
    return _emit_generic_field(node, field, cfg, bindings)


def _emit_class_field(
    node: ast.ClassDef,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if field == "body":
        return _emit_list(node.body, cfg, bindings.enter(node))
    return _emit_generic_field(node, field, cfg, bindings)


def _emit_comprehension_field(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    inner = bindings.enter(node)
    if field == "generators":
        return _emit_generators(node.generators, cfg, outer=bindings, inner=inner)
    return _emit_value(vars(node).get(field), cfg, field=field, bindings=inner)


def _emit_generators(
    generators: Sequence[ast.comprehension],
    cfg: NormalizationConfig,
    *,
    outer: BindingContext,
    inner: BindingContext,
) -> str:
    # Python evaluates the leftmost iterable in the enclosing scope and
    # everything else inside the comprehension; the wire says the same.
    items = ",".join(
        _emit_comprehension(
            generator,
            cfg,
            inner=inner,
            iter_bindings=outer if index == 0 else inner,
        )
        for index, generator in enumerate(generators)
    )
    return "[" + items + "]"


def _emit_comprehension(
    node: ast.comprehension,
    cfg: NormalizationConfig,
    *,
    inner: BindingContext,
    iter_bindings: BindingContext,
) -> str:
    node_type = type(node)
    fields = _WIRE_FIELDS.get(node_type)
    if fields is None:
        raise WireUnsupportedNode(f"unsupported AST node: {node_type.__name__}")
    _check_fields(node, fields)
    parts: list[str] = [node_type.__name__, "("]
    for index, field in enumerate(fields):
        if index:
            parts.append(",")
        scope = iter_bindings if field == "iter" else inner
        parts.extend(
            (
                field,
                "=",
                _emit_value(vars(node).get(field), cfg, field=field, bindings=scope),
            )
        )
    parts.append(")")
    return "".join(parts)


def _emit_arg_field(
    node: ast.arg,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if field == "annotation" and cfg.ignore_type_annotations:
        return "None"
    return _emit_generic_field(node, field, cfg, bindings)


def _emit_capture_or_generic_field(
    node: ast.AST,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and field == "name":
        return _emit_capture_name(vars(node).get(field), cfg)
    if isinstance(node, ast.MatchMapping) and field == "rest":
        return _emit_capture_name(node.rest, cfg)
    if type(node).__name__ == "Interpolation" and field == "str":
        return "_CONST_"
    if isinstance(node, ast.TypeIgnore) and field == "tag":
        return "_CONST_"
    return _emit_generic_field(node, field, cfg, bindings)


def _emit_generic_field(
    node: ast.AST,
    field: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    field_value = vars(node).get(field)
    return _emit_value(field_value, cfg, field=field, bindings=bindings)


def _emit_value(
    value: object,
    cfg: NormalizationConfig,
    *,
    field: str,
    bindings: BindingContext,
) -> str:
    if isinstance(value, ast.AST):
        return _emit_node(value, cfg, bindings)
    if isinstance(value, list):
        return _emit_list(value, cfg, bindings)
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


def _emit_list(
    values: Sequence[object],
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    items = ",".join(
        _emit_value(value, cfg, field="list", bindings=bindings) for value in values
    )
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
    bindings: BindingContext,
) -> str:
    return f"Name(id={_symbol_identifier(node.id, cfg, bindings)})"


def _symbol_identifier(
    name: str,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    """Emit one root symbol by the role it is bound to (role table, section 2)."""

    if not cfg.normalize_names or name.startswith(CFG_META_PREFIX):
        return _emit_identifier(name)
    binding = bindings.lookup(name)
    if binding is None:
        # No binding anywhere — a builtin or a name defined elsewhere. Unknown
        # identity is preserved literally so two unknowns never merge.
        return _emit_identifier(name)
    if binding.role == "self":
        return "_SELF_"
    if binding.role == "cls":
        return "_CLS_"
    if binding.role == "import":
        return _emit_identifier(binding.identity)
    if binding.role == "local":
        return "_VAR_"
    return _emit_identifier(name)


def _emit_attribute(
    node: ast.Attribute,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    canonical = _canonical_chain_identity(node, cfg, bindings)
    if canonical is not None:
        return f"Name(id={_emit_identifier(canonical)})"
    value = _emit_node(node.value, cfg, bindings)
    # Attributes are always preserved: an attribute name is a symbol, not a
    # variable, and erasing it is what made `json.dumps` and `yaml.dumps`
    # indistinguishable (role table row 7).
    return f"Attribute(value={value},attr={_emit_identifier(node.attr)})"


def _canonical_chain_identity(
    node: ast.Attribute,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str | None:
    """Return the dotted identity of an attribute chain rooted at an import.

    A resolved identity always emits as a single ``Name`` holding its canonical
    dotted path, whatever the syntax used to reach it, so ``json.dumps(x)``,
    ``j.dumps(x)`` and a bare ``dumps(x)`` from ``from json import dumps`` all
    produce the same callee wire.
    """

    if not cfg.normalize_names:
        return None
    attributes: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id.startswith(CFG_META_PREFIX):
        return None
    binding = bindings.lookup(current.id)
    if binding is None or binding.role != "import":
        return None
    attributes.reverse()
    return ".".join((binding.identity, *attributes))


def _emit_aug_assign(
    node: ast.AugAssign,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    target = _emit_node(node.target, cfg, bindings)
    operation = _emit_node(node.op, cfg, bindings)
    value = _emit_node(node.value, cfg, bindings)
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


def _emit_negated_compare(
    node: ast.UnaryOp,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str | None:
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
    left = _emit_node(operand.left, cfg, bindings)
    comparator = _emit_node(operand.comparators[0], cfg, bindings)
    return (
        "Compare(left="
        + left
        + ",ops=["
        + operation_wire
        + "],comparators=["
        + comparator
        + "])"
    )


def _emit_bin_op(
    node: ast.BinOp,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    left = _emit_node(node.left, cfg, bindings)
    right = _emit_node(node.right, cfg, bindings)
    if (
        isinstance(node.op, (ast.Add, ast.Mult, ast.BitOr, ast.BitAnd, ast.BitXor))
        and _is_proven_commutative_operand(node.left, node.op)
        and _is_proven_commutative_operand(node.right, node.op)
        and right < left
    ):
        left, right = right, left
    operation = _emit_node(node.op, cfg, bindings)
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
