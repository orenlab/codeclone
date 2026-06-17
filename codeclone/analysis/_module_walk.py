# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple, TypeGuard

from .. import qualnames as _qualnames
from ..models import (
    DeadCandidate,
    FunctionRelationshipFacts,
    ModuleDep,
    RelationshipOriginLane,
    RelationshipRecord,
)
from .class_metrics import _node_line_span
from .parser import (
    _build_declaration_token_index,
    _declaration_end_line,
    _DeclarationTokenIndexKey,
    _source_tokens,
)
from .suppressions import (
    DeclarationTarget,
    bind_suppressions_to_declarations,
    build_suppression_index,
    extract_suppression_directives,
    suppression_target_key,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .suppressions import SuppressionTargetKey


_NamedDeclarationNode = _qualnames.FunctionNode | ast.ClassDef
_PROTOCOL_MODULE_NAMES = frozenset({"typing", "typing_extensions"})
_NON_RUNTIME_DECORATOR_SYMBOLS = frozenset({"overload", "abstractmethod"})
_PYDANTIC_MODULE_NAMES = frozenset(
    {
        "pydantic",
        "pydantic.class_validators",
        "pydantic.deprecated.class_validators",
        "pydantic.functional_serializers",
        "pydantic.functional_validators",
        "pydantic.v1",
        "pydantic.v1.class_validators",
    }
)
_PYDANTIC_DECORATOR_NAMES = frozenset(
    {
        "computed_field",
        "field_serializer",
        "field_validator",
        "model_serializer",
        "model_validator",
        "root_validator",
        "validator",
    }
)
# Cohesion ignores declarative validation/serialization hooks because they are
# field-local framework callbacks, not instance-behavior methods. `computed_field`
# is deliberately excluded: it commonly reads `self.*` and participates in real
# object cohesion, so it stays in the LCOM4 graph.
_COHESION_IGNORED_PYDANTIC_HOOKS = _PYDANTIC_DECORATOR_NAMES - frozenset(
    {"computed_field"}
)


def _resolve_import_target(
    module_name: str,
    import_node: ast.ImportFrom,
) -> str:
    if import_node.level <= 0:
        return import_node.module or ""

    parent_parts = module_name.split(".")
    keep = max(0, len(parent_parts) - import_node.level)
    prefix = parent_parts[:keep]
    if import_node.module:
        return ".".join([*prefix, import_node.module])
    return ".".join(prefix)


@dataclass(slots=True)
class _ModuleWalkState:
    import_names: set[str] = field(default_factory=set)
    deps: list[ModuleDep] = field(default_factory=list)
    referenced_names: set[str] = field(default_factory=set)
    imported_symbol_bindings: dict[str, set[str]] = field(default_factory=dict)
    imported_module_aliases: dict[str, str] = field(default_factory=dict)
    name_nodes: list[ast.Name] = field(default_factory=list)
    attr_nodes: list[ast.Attribute] = field(default_factory=list)
    exported_names: set[str] = field(default_factory=set)
    lazy_export_bindings: dict[str, set[str]] = field(default_factory=dict)
    has_module_getattr: bool = False
    protocol_symbol_aliases: set[str] = field(default_factory=lambda: {"Protocol"})
    protocol_module_aliases: set[str] = field(
        default_factory=lambda: set(_PROTOCOL_MODULE_NAMES)
    )
    non_runtime_decorator_aliases: set[str] = field(
        default_factory=lambda: set(_NON_RUNTIME_DECORATOR_SYMBOLS)
    )
    pydantic_module_aliases: set[str] = field(default_factory=lambda: {"pydantic"})
    cohesion_ignored_decorator_aliases: set[str] = field(
        default_factory=lambda: set(_COHESION_IGNORED_PYDANTIC_HOOKS)
    )


def _append_module_dep(
    *,
    module_name: str,
    target: str,
    import_type: Literal["import", "from_import"],
    line: int,
    state: _ModuleWalkState,
) -> None:
    state.deps.append(
        ModuleDep(
            source=module_name,
            target=target,
            import_type=import_type,
            line=line,
        )
    )


def _collect_import_node(
    *,
    node: ast.Import,
    module_name: str,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
) -> None:
    line = int(getattr(node, "lineno", 0))
    for alias in node.names:
        alias_name = alias.asname or alias.name.split(".", 1)[0]
        state.import_names.add(alias_name)
        _append_module_dep(
            module_name=module_name,
            target=alias.name,
            import_type="import",
            line=line,
            state=state,
        )
        if collect_referenced_names:
            state.imported_module_aliases[alias_name] = alias.name
        if alias.name in _PROTOCOL_MODULE_NAMES:
            state.protocol_module_aliases.add(alias_name)
        if alias.name in _PYDANTIC_MODULE_NAMES or alias.name.startswith("pydantic."):
            state.pydantic_module_aliases.add(alias_name)


def _matching_import_aliases(
    node: ast.ImportFrom,
    names: frozenset[str],
) -> set[str]:
    return {alias.asname or alias.name for alias in node.names if alias.name in names}


def _dotted_expr_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        prefix = _dotted_expr_name(expr.value)
        if prefix is None:
            return None
        return f"{prefix}.{expr.attr}"
    if isinstance(expr, ast.Subscript):
        return _dotted_expr_name(expr.value)
    return None


def _decorator_expr_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Call):
        return _dotted_expr_name(expr.func)
    return _dotted_expr_name(expr)


def _string_literals_from_export_value(value: ast.AST) -> tuple[str, ...]:
    match value:
        case ast.Constant(value=str() as name):
            return (name,)
        case ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts):
            return tuple(
                item.value
                for item in elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            return (
                *_string_literals_from_export_value(left),
                *_string_literals_from_export_value(right),
            )
        case _:
            return ()


def _string_mapping_from_literal_dict(value: ast.AST) -> dict[str, str]:
    if not isinstance(value, ast.Dict):
        return {}
    mapping: dict[str, str] = {}
    for key, val in zip(value.keys, value.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(val, ast.Constant)
            and isinstance(val.value, str)
        ):
            mapping[key.value] = val.value
    return mapping


def _collect_all_export_node(node: ast.AST, state: _ModuleWalkState) -> None:
    match node:
        case ast.Assign(targets=targets, value=value):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in targets
            ):
                state.exported_names.update(_string_literals_from_export_value(value))
        case ast.AnnAssign(target=ast.Name(id="__all__"), value=value):
            if value is not None:
                state.exported_names.update(_string_literals_from_export_value(value))
        case ast.AugAssign(target=ast.Name(id="__all__"), value=value):
            state.exported_names.update(_string_literals_from_export_value(value))
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(value=ast.Name(id="__all__"), attr="append"),
                args=[arg],
            )
        ):
            state.exported_names.update(_string_literals_from_export_value(arg))
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(value=ast.Name(id="__all__"), attr="extend"),
                args=[arg],
            )
        ):
            state.exported_names.update(_string_literals_from_export_value(arg))
        case _:
            pass


def _collect_lazy_export_node(node: ast.AST, state: _ModuleWalkState) -> None:
    match node:
        case ast.Assign(targets=targets, value=value):
            names = {target.id for target in targets if isinstance(target, ast.Name)}
        case ast.AnnAssign(target=ast.Name(id=name), value=value):
            names = {name}
        case (
            ast.FunctionDef(name="__getattr__")
            | ast.AsyncFunctionDef(name="__getattr__")
        ):
            state.has_module_getattr = True
            return
        case _:
            return
    if "_EXPORTS" not in names or value is None:
        return
    for exported_name, module_path in _string_mapping_from_literal_dict(value).items():
        state.lazy_export_bindings.setdefault(exported_name, set()).add(module_path)


def _collect_module_all_exports(tree: ast.AST, state: _ModuleWalkState) -> None:
    if not isinstance(tree, ast.Module):
        return
    for statement in tree.body:
        _collect_all_export_node(statement, state)
        _collect_lazy_export_node(statement, state)


def _literal_getattr_name(value: ast.AST | None) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    if not isinstance(value.func, ast.Name) or value.func.id != "getattr":
        return None
    if len(value.args) < 2:
        return None
    attr_arg = value.args[1]
    if not isinstance(attr_arg, ast.Constant) or not isinstance(attr_arg.value, str):
        return None
    if attr_arg.value.isidentifier():
        return attr_arg.value
    return None


def _iter_runtime_callable_scopes(
    tree: ast.AST,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    if not isinstance(tree, ast.Module):
        return
    stack = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node
            continue
        if isinstance(node, ast.ClassDef):
            stack.extend(reversed(node.body))


def _iter_scope_body_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _dynamic_getattr_names_from_scope(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    getattr_bindings: dict[str, str] = {}
    callable_guards: set[str] = set()
    called_locals: set[str] = set()
    for scope_node in _iter_scope_body_nodes(node.body):
        match scope_node:
            case ast.Assign(targets=targets, value=value):
                attr_name = _literal_getattr_name(value)
                if attr_name is not None:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            getattr_bindings[target.id] = attr_name
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                attr_name = _literal_getattr_name(value)
                if attr_name is not None:
                    getattr_bindings[name] = attr_name
            case ast.Call(
                func=ast.Name(id="callable"),
                args=[ast.Name(id=name), *_],
            ):
                callable_guards.add(name)
            case ast.Call(func=ast.Name(id=name)):
                called_locals.add(name)
            case _:
                pass
    return {
        attr_name
        for local_name, attr_name in getattr_bindings.items()
        if local_name in callable_guards and local_name in called_locals
    }


def _collect_dynamic_getattr_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for scope in _iter_runtime_callable_scopes(tree):
        names.update(_dynamic_getattr_names_from_scope(scope))
    return names


def _local_export_qualname(
    *,
    module_name: str,
    exported_name: str,
    functions_by_name: dict[str, str],
    classes_by_name: dict[str, str],
) -> str | None:
    local_qualname = functions_by_name.get(exported_name)
    if local_qualname is None:
        local_qualname = classes_by_name.get(exported_name)
    if local_qualname is None:
        return None
    return f"{module_name}:{local_qualname}"


def _collect_import_from_node(
    *,
    node: ast.ImportFrom,
    module_name: str,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
) -> None:
    target = _resolve_import_target(module_name, node)
    if target:
        state.import_names.add(target.split(".", 1)[0])
        _append_module_dep(
            module_name=module_name,
            target=target,
            import_type="from_import",
            line=int(getattr(node, "lineno", 0)),
            state=state,
        )

    if node.module in _PROTOCOL_MODULE_NAMES:
        state.protocol_symbol_aliases.update(
            _matching_import_aliases(node, frozenset({"Protocol"}))
        )

    if node.module in _PYDANTIC_MODULE_NAMES or str(node.module).startswith(
        "pydantic."
    ):
        state.non_runtime_decorator_aliases.update(
            _matching_import_aliases(node, _PYDANTIC_DECORATOR_NAMES)
        )
        state.cohesion_ignored_decorator_aliases.update(
            _matching_import_aliases(node, _COHESION_IGNORED_PYDANTIC_HOOKS)
        )

    if not collect_referenced_names or not target:
        return

    for alias in node.names:
        if alias.name == "*":
            continue
        alias_name = alias.asname or alias.name
        state.imported_symbol_bindings.setdefault(alias_name, set()).add(
            f"{target}:{alias.name}"
        )


def _collect_load_reference_node(
    *,
    node: ast.AST,
    state: _ModuleWalkState,
) -> None:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        state.referenced_names.add(node.id)
        state.name_nodes.append(node)
        return
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        state.referenced_names.add(node.attr)
        state.attr_nodes.append(node)


@dataclass(frozen=True, slots=True)
class _RelationshipImportIndex:
    symbol_bindings: dict[str, frozenset[str]]
    module_bindings: dict[str, frozenset[str]]
    module_shadowed_names: frozenset[str]


def _iter_relationship_scope_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(
            node,
            ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
        ):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _freeze_relationship_bindings(
    bindings: dict[str, set[str]],
) -> dict[str, frozenset[str]]:
    return {
        name: frozenset(sorted(targets)) for name, targets in sorted(bindings.items())
    }


def _scope_declaration_binding_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    if isinstance(node, ast.ExceptHandler) and node.name:
        return node.name
    if isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
        return node.name
    return None


def _collect_relationship_import_index(
    *,
    tree: ast.AST,
    module_name: str,
) -> _RelationshipImportIndex:
    symbol_bindings: dict[str, set[str]] = {}
    module_bindings: dict[str, set[str]] = {}
    shadowed_names: set[str] = set()
    if not isinstance(tree, ast.Module):
        return _RelationshipImportIndex({}, {}, frozenset())

    for node in _iter_relationship_scope_nodes(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                alias_name = alias.asname or alias.name.split(".", 1)[0]
                module_bindings.setdefault(alias_name, set()).add(alias.name)
            continue
        if isinstance(node, ast.ImportFrom):
            target = _resolve_import_target(module_name, node)
            if target:
                for alias in node.names:
                    if alias.name != "*":
                        alias_name = alias.asname or alias.name
                        symbol_bindings.setdefault(alias_name, set()).add(
                            f"{target}:{alias.name}"
                        )
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            shadowed_names.add(node.id)
            continue
        declaration_name = _scope_declaration_binding_name(node)
        if declaration_name is not None:
            shadowed_names.add(declaration_name)

    return _RelationshipImportIndex(
        symbol_bindings=_freeze_relationship_bindings(symbol_bindings),
        module_bindings=_freeze_relationship_bindings(module_bindings),
        module_shadowed_names=frozenset(sorted(shadowed_names)),
    )


def _function_parameter_names(node: _qualnames.FunctionNode) -> set[str]:
    positional = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    names = {arg.arg for arg in positional}
    if node.args.vararg is not None:
        names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        names.add(node.args.kwarg.arg)
    return names


def _caller_local_bindings(node: _qualnames.FunctionNode) -> frozenset[str]:
    bound_names = _function_parameter_names(node)
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()
    for scope_node in _iter_relationship_scope_nodes(node.body):
        if isinstance(scope_node, ast.Name) and isinstance(
            scope_node.ctx, ast.Store | ast.Del
        ):
            bound_names.add(scope_node.id)
        elif isinstance(scope_node, ast.Import):
            bound_names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in scope_node.names
            )
        elif isinstance(scope_node, ast.ImportFrom):
            bound_names.update(
                alias.asname or alias.name
                for alias in scope_node.names
                if alias.name != "*"
            )
        elif isinstance(scope_node, ast.Global):
            global_names.update(scope_node.names)
        elif isinstance(scope_node, ast.Nonlocal):
            nonlocal_names.update(scope_node.names)
        else:
            declaration_name = _scope_declaration_binding_name(scope_node)
            if declaration_name is not None:
                bound_names.add(declaration_name)
    bound_names.difference_update(global_names)
    bound_names.difference_update(nonlocal_names)
    return frozenset(sorted(bound_names))


def _first_parameter_name(node: _qualnames.FunctionNode) -> str | None:
    positional = [*node.args.posonlyargs, *node.args.args]
    return positional[0].arg if positional else None


def _decorator_simple_names(node: _qualnames.FunctionNode) -> frozenset[str]:
    names: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return frozenset(names)


def _relationship_expression(node: ast.AST) -> str | None:
    try:
        expression = ast.unparse(node)
    except (TypeError, ValueError):
        return None
    return expression or None


def _single_relationship_target(
    targets: frozenset[str] | None,
    *,
    resolved_rule: str,
) -> tuple[str | None, str]:
    if not targets:
        return None, "unresolved_name"
    if len(targets) != 1:
        return None, "ambiguous_import"
    return next(iter(targets)), resolved_rule


def _resolve_relationship_expression(
    node: ast.expr,
    *,
    module_name: str,
    imports: _RelationshipImportIndex,
    caller_bindings: frozenset[str],
    top_level_function_names: frozenset[str],
    top_level_class_names: frozenset[str],
    local_method_qualnames: frozenset[str],
    enclosing_class_local: str | None,
    receiver_name: str | None,
) -> tuple[str | None, str]:
    if isinstance(node, ast.Name):
        import_targets = imports.symbol_bindings.get(node.id)
        if import_targets and (
            node.id in caller_bindings or node.id in imports.module_shadowed_names
        ):
            return None, "local_shadowing"
        if import_targets:
            return _single_relationship_target(
                import_targets,
                resolved_rule="imported_symbol",
            )
        if node.id in caller_bindings:
            return None, "unresolved_name"
        if node.id in top_level_function_names:
            return f"{module_name}:{node.id}", "same_module_function"
        return None, "unresolved_name"

    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base_name = node.value.id
        import_targets = imports.module_bindings.get(base_name)
        if import_targets and (
            base_name in caller_bindings or base_name in imports.module_shadowed_names
        ):
            return None, "local_shadowing"
        if import_targets:
            target_module, rule = _single_relationship_target(
                import_targets,
                resolved_rule="imported_module_attribute",
            )
            if target_module is not None:
                return f"{target_module}:{node.attr}", rule
            return None, rule
        # The receiver parameter (self/cls) is itself a caller binding, so the
        # self/cls case must precede the generic caller-shadow guard below.
        if (
            receiver_name is not None
            and enclosing_class_local is not None
            and base_name == receiver_name
        ):
            candidate = f"{module_name}:{enclosing_class_local}.{node.attr}"
            if candidate in local_method_qualnames:
                return candidate, "self_or_cls_method"
            return None, "unresolved_dynamic"
        if base_name in top_level_class_names and base_name not in caller_bindings:
            candidate = f"{module_name}:{base_name}.{node.attr}"
            if candidate in local_method_qualnames:
                return candidate, "same_module_class_method"
            return None, "unresolved_dynamic"
    return None, "unresolved_dynamic"


def _relationship_record(
    *,
    relation_kind: Literal["call", "reference"],
    origin_lane: RelationshipOriginLane,
    source_qualname: str,
    target_qualname: str | None,
    filepath: str,
    node: ast.expr,
    resolution_rule: str,
) -> RelationshipRecord:
    return RelationshipRecord(
        relation_kind=relation_kind,
        resolution_status="resolved" if target_qualname is not None else "unresolved",
        origin_lane=origin_lane,
        source_qualname=source_qualname,
        target_qualname=target_qualname,
        path=filepath,
        line=max(1, int(getattr(node, "lineno", 1))),
        expression=_relationship_expression(node),
        resolution_rule=resolution_rule,
    )


def _relationship_record_sort_key(
    record: RelationshipRecord,
) -> tuple[str, str, str, str, int, str, str]:
    return (
        record.relation_kind,
        record.origin_lane,
        record.target_qualname or "",
        record.path,
        record.line,
        record.resolution_rule or "",
        record.expression or "",
    )


def _is_relationship_reference_node(
    node: ast.AST,
    *,
    call_function_node_ids: set[int],
) -> TypeGuard[ast.Name | ast.Attribute]:
    return (
        id(node) not in call_function_node_ids
        and isinstance(node, ast.Name | ast.Attribute)
        and isinstance(node.ctx, ast.Load)
    )


def _collect_function_relationship_facts(
    *,
    tree: ast.AST,
    module_name: str,
    filepath: str,
    collector: _qualnames.QualnameCollector,
    origin_lane: RelationshipOriginLane,
) -> tuple[FunctionRelationshipFacts, ...]:
    imports = _collect_relationship_import_index(
        tree=tree,
        module_name=module_name,
    )
    top_level_function_names = frozenset(
        local_name for local_name, _node in collector.units if "." not in local_name
    )
    top_level_class_names = frozenset(
        class_qualname
        for class_qualname, _node in collector.class_nodes
        if "." not in class_qualname
    )
    local_method_qualnames = frozenset(
        f"{module_name}:{local_name}"
        for local_name, _node in collector.units
        if "." in local_name
    )
    facts: list[FunctionRelationshipFacts] = []
    for local_name, function_node in collector.units:
        source_qualname = f"{module_name}:{local_name}"
        caller_bindings = _caller_local_bindings(function_node)
        # The enclosing class of a method is the qualname segment before its own
        # name; top-level functions have none. The receiver (self/cls) is the
        # first parameter, but only for non-static methods — a staticmethod's
        # first parameter is an ordinary value, not a receiver.
        enclosing_class_local = (
            local_name.rsplit(".", 1)[0] if "." in local_name else None
        )
        receiver_name = (
            _first_parameter_name(function_node)
            if enclosing_class_local is not None
            and "staticmethod" not in _decorator_simple_names(function_node)
            else None
        )
        scope_nodes = tuple(_iter_relationship_scope_nodes(function_node.body))
        calls = tuple(node for node in scope_nodes if isinstance(node, ast.Call))
        call_function_node_ids = {
            id(descendant) for call in calls for descendant in ast.walk(call.func)
        }
        records: list[RelationshipRecord] = []
        for call in calls:
            target_qualname, resolution_rule = _resolve_relationship_expression(
                call.func,
                module_name=module_name,
                imports=imports,
                caller_bindings=caller_bindings,
                top_level_function_names=top_level_function_names,
                top_level_class_names=top_level_class_names,
                local_method_qualnames=local_method_qualnames,
                enclosing_class_local=enclosing_class_local,
                receiver_name=receiver_name,
            )
            records.append(
                _relationship_record(
                    relation_kind="call",
                    origin_lane=origin_lane,
                    source_qualname=source_qualname,
                    target_qualname=target_qualname,
                    filepath=filepath,
                    node=call.func,
                    resolution_rule=resolution_rule,
                )
            )
        for node in scope_nodes:
            if not _is_relationship_reference_node(
                node,
                call_function_node_ids=call_function_node_ids,
            ):
                continue
            target_qualname, resolution_rule = _resolve_relationship_expression(
                node,
                module_name=module_name,
                imports=imports,
                caller_bindings=caller_bindings,
                top_level_function_names=top_level_function_names,
                top_level_class_names=top_level_class_names,
                local_method_qualnames=local_method_qualnames,
                enclosing_class_local=enclosing_class_local,
                receiver_name=receiver_name,
            )
            if target_qualname is not None:
                records.append(
                    _relationship_record(
                        relation_kind="reference",
                        origin_lane=origin_lane,
                        source_qualname=source_qualname,
                        target_qualname=target_qualname,
                        filepath=filepath,
                        node=node,
                        resolution_rule=resolution_rule,
                    )
                )
        if records:
            facts.append(
                FunctionRelationshipFacts(
                    source_qualname=source_qualname,
                    relationships=tuple(
                        sorted(records, key=_relationship_record_sort_key)
                    ),
                )
            )
    return tuple(sorted(facts, key=lambda item: item.source_qualname))


def _is_protocol_class(
    class_node: ast.ClassDef,
    *,
    protocol_symbol_aliases: frozenset[str],
    protocol_module_aliases: frozenset[str],
) -> bool:
    for base in class_node.bases:
        base_name = _dotted_expr_name(base)
        if base_name is None:
            continue
        if base_name in protocol_symbol_aliases:
            return True
        if "." in base_name and base_name.rsplit(".", 1)[-1] == "Protocol":
            module_alias = base_name.rsplit(".", 1)[0]
            if module_alias in protocol_module_aliases:
                return True
    return False


def _is_known_pydantic_decorator(
    name: str,
    *,
    pydantic_module_aliases: frozenset[str],
) -> bool:
    terminal = name.rsplit(".", 1)[-1]
    if terminal not in _PYDANTIC_DECORATOR_NAMES or "." not in name:
        return False
    module_alias = name.rsplit(".", 1)[0]
    return any(
        module_alias == alias or module_alias.startswith(f"{alias}.")
        for alias in pydantic_module_aliases
    )


def _is_cohesion_ignored_decorator(
    name: str,
    *,
    cohesion_ignored_decorator_aliases: frozenset[str],
    pydantic_module_aliases: frozenset[str],
) -> bool:
    # Bare or no-asname form: the decorator name matches a known hook alias.
    if name in cohesion_ignored_decorator_aliases:
        return True
    # Dotted form, e.g. pydantic.field_validator.
    terminal = name.rsplit(".", 1)[-1]
    if terminal not in _COHESION_IGNORED_PYDANTIC_HOOKS or "." not in name:
        return False
    module_alias = name.rsplit(".", 1)[0]
    return any(
        module_alias == alias or module_alias.startswith(f"{alias}.")
        for alias in pydantic_module_aliases
    )


def _cohesion_ignored_method_names(
    class_node: ast.ClassDef,
    *,
    protocol_symbol_aliases: frozenset[str],
    protocol_module_aliases: frozenset[str],
    pydantic_module_aliases: frozenset[str],
    cohesion_ignored_decorator_aliases: frozenset[str],
) -> frozenset[str]:
    """Return method names excluded from LCOM4 cohesion for this class.

    Protocol declarations contribute all their method names (the whole class is
    an interface surface). Other classes contribute only methods decorated with
    Pydantic validator/serializer hooks. ``computed_field`` is never ignored
    because it commonly reads ``self.*`` and carries real cohesion.
    """
    methods = [
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if _is_protocol_class(
        class_node,
        protocol_symbol_aliases=protocol_symbol_aliases,
        protocol_module_aliases=protocol_module_aliases,
    ):
        return frozenset(method.name for method in methods)

    ignored: set[str] = set()
    for method in methods:
        for decorator in method.decorator_list:
            name = _decorator_expr_name(decorator)
            if name is None:
                continue
            if _is_cohesion_ignored_decorator(
                name,
                cohesion_ignored_decorator_aliases=cohesion_ignored_decorator_aliases,
                pydantic_module_aliases=pydantic_module_aliases,
            ):
                ignored.add(method.name)
                break
    return frozenset(ignored)


def _is_non_runtime_candidate(
    node: _qualnames.FunctionNode,
    *,
    non_runtime_decorator_aliases: frozenset[str] = frozenset(
        _NON_RUNTIME_DECORATOR_SYMBOLS
    ),
    pydantic_module_aliases: frozenset[str] = frozenset({"pydantic"}),
) -> bool:
    for decorator in node.decorator_list:
        name = _decorator_expr_name(decorator)
        if name is None:
            continue
        if name in non_runtime_decorator_aliases:
            return True
        terminal = name.rsplit(".", 1)[-1]
        if terminal in _NON_RUNTIME_DECORATOR_SYMBOLS:
            return True
        if _is_known_pydantic_decorator(
            name,
            pydantic_module_aliases=pydantic_module_aliases,
        ):
            return True
    return False


def _dead_candidate_kind(local_name: str) -> Literal["function", "method"]:
    return "method" if "." in local_name else "function"


def _should_skip_dead_candidate(
    local_name: str,
    node: _qualnames.FunctionNode,
    *,
    protocol_class_qualnames: set[str],
    non_runtime_decorator_aliases: frozenset[str],
    pydantic_module_aliases: frozenset[str],
) -> bool:
    if _is_non_runtime_candidate(
        node,
        non_runtime_decorator_aliases=non_runtime_decorator_aliases,
        pydantic_module_aliases=pydantic_module_aliases,
    ):
        return True
    if "." not in local_name:
        return False
    owner_qualname = local_name.rsplit(".", 1)[0]
    return owner_qualname in protocol_class_qualnames


def _build_dead_candidate(
    *,
    module_name: str,
    local_name: str,
    node: _NamedDeclarationNode,
    filepath: str,
    kind: Literal["class", "function", "method"],
    suppression_index: Mapping[SuppressionTargetKey, tuple[str, ...]],
    start_line: int,
    end_line: int,
) -> DeadCandidate:
    qualname = f"{module_name}:{local_name}"
    return DeadCandidate(
        qualname=qualname,
        local_name=node.name,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        kind=kind,
        suppressed_rules=suppression_index.get(
            suppression_target_key(
                filepath=filepath,
                qualname=qualname,
                start_line=start_line,
                end_line=end_line,
                kind=kind,
            ),
            (),
        ),
    )


def _dead_candidate_for_unit(
    *,
    module_name: str,
    local_name: str,
    node: _qualnames.FunctionNode,
    filepath: str,
    suppression_index: Mapping[SuppressionTargetKey, tuple[str, ...]],
    protocol_class_qualnames: set[str],
    non_runtime_decorator_aliases: frozenset[str],
    pydantic_module_aliases: frozenset[str],
) -> DeadCandidate | None:
    span = _node_line_span(node)
    if span is None:
        return None
    if _should_skip_dead_candidate(
        local_name,
        node,
        protocol_class_qualnames=protocol_class_qualnames,
        non_runtime_decorator_aliases=non_runtime_decorator_aliases,
        pydantic_module_aliases=pydantic_module_aliases,
    ):
        return None
    start, end = span
    return _build_dead_candidate(
        module_name=module_name,
        local_name=local_name,
        node=node,
        filepath=filepath,
        kind=_dead_candidate_kind(local_name),
        suppression_index=suppression_index,
        start_line=start,
        end_line=end,
    )


def _resolve_referenced_qualnames(
    *,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    state: _ModuleWalkState,
) -> frozenset[str]:
    top_level_class_by_name = {
        class_qualname: class_qualname
        for class_qualname, _class_node in collector.class_nodes
        if "." not in class_qualname
    }
    top_level_function_by_name = {
        local_name: local_name
        for local_name, _node in collector.units
        if "." not in local_name
    }
    local_method_qualnames = frozenset(
        f"{module_name}:{local_name}"
        for local_name, _node in collector.units
        if "." in local_name
    )

    resolved: set[str] = set()
    for name_node in state.name_nodes:
        for qualname in state.imported_symbol_bindings.get(name_node.id, ()):
            resolved.add(qualname)

    for attr_node in state.attr_nodes:
        base = attr_node.value
        if isinstance(base, ast.Name):
            imported_module = state.imported_module_aliases.get(base.id)
            if imported_module is not None:
                resolved.add(f"{imported_module}:{attr_node.attr}")
            else:
                class_qualname = top_level_class_by_name.get(base.id)
                if class_qualname is not None:
                    local_method_qualname = (
                        f"{module_name}:{class_qualname}.{attr_node.attr}"
                    )
                    if local_method_qualname in local_method_qualnames:
                        resolved.add(local_method_qualname)

    for exported_name in state.exported_names:
        local_export_qualname = _local_export_qualname(
            module_name=module_name,
            exported_name=exported_name,
            functions_by_name=top_level_function_by_name,
            classes_by_name=top_level_class_by_name,
        )
        if local_export_qualname is not None:
            resolved.add(local_export_qualname)
            continue
        resolved.update(state.imported_symbol_bindings.get(exported_name, ()))
        if state.has_module_getattr:
            for module_path in state.lazy_export_bindings.get(exported_name, ()):
                resolved.add(f"{module_path}:{exported_name}")

    return frozenset(resolved)


class _ModuleWalkResult(NamedTuple):
    import_names: frozenset[str]
    module_deps: tuple[ModuleDep, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    protocol_symbol_aliases: frozenset[str]
    protocol_module_aliases: frozenset[str]
    non_runtime_decorator_aliases: frozenset[str]
    pydantic_module_aliases: frozenset[str]
    cohesion_ignored_decorator_aliases: frozenset[str]


def _collect_module_walk_data(
    *,
    tree: ast.AST,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    collect_referenced_names: bool,
) -> _ModuleWalkResult:
    """Single ast.walk that collects imports, deps, names, qualnames & protocol aliases.

    Reduces the hot path to one tree walk plus one local qualname resolution phase.
    """
    state = _ModuleWalkState()
    _collect_module_all_exports(tree, state)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _collect_import_node(
                node=node,
                module_name=module_name,
                state=state,
                collect_referenced_names=collect_referenced_names,
            )
        elif isinstance(node, ast.ImportFrom):
            _collect_import_from_node(
                node=node,
                module_name=module_name,
                state=state,
                collect_referenced_names=collect_referenced_names,
            )
        elif collect_referenced_names:
            _collect_load_reference_node(node=node, state=state)
    if collect_referenced_names:
        state.referenced_names.update(_collect_dynamic_getattr_names(tree))

    deps_sorted = tuple(
        sorted(
            state.deps,
            key=lambda dep: (dep.source, dep.target, dep.import_type, dep.line),
        )
    )
    resolved = (
        _resolve_referenced_qualnames(
            module_name=module_name,
            collector=collector,
            state=state,
        )
        if collect_referenced_names
        else frozenset()
    )

    return _ModuleWalkResult(
        import_names=frozenset(state.import_names),
        module_deps=deps_sorted,
        referenced_names=frozenset(state.referenced_names),
        referenced_qualnames=resolved,
        protocol_symbol_aliases=frozenset(state.protocol_symbol_aliases),
        protocol_module_aliases=frozenset(state.protocol_module_aliases),
        non_runtime_decorator_aliases=frozenset(state.non_runtime_decorator_aliases),
        pydantic_module_aliases=frozenset(state.pydantic_module_aliases),
        cohesion_ignored_decorator_aliases=frozenset(
            state.cohesion_ignored_decorator_aliases
        ),
    )


def _collect_dead_candidates(
    *,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    protocol_symbol_aliases: frozenset[str] = frozenset({"Protocol"}),
    protocol_module_aliases: frozenset[str] = frozenset(
        {"typing", "typing_extensions"}
    ),
    non_runtime_decorator_aliases: frozenset[str] = frozenset(
        _NON_RUNTIME_DECORATOR_SYMBOLS
    ),
    pydantic_module_aliases: frozenset[str] = frozenset({"pydantic"}),
    suppression_rules_by_target: Mapping[SuppressionTargetKey, tuple[str, ...]]
    | None = None,
) -> tuple[DeadCandidate, ...]:
    protocol_class_qualnames = {
        class_qualname
        for class_qualname, class_node in collector.class_nodes
        if _is_protocol_class(
            class_node,
            protocol_symbol_aliases=protocol_symbol_aliases,
            protocol_module_aliases=protocol_module_aliases,
        )
    }

    candidates: list[DeadCandidate] = []
    suppression_index = (
        suppression_rules_by_target if suppression_rules_by_target is not None else {}
    )
    for local_name, node in collector.units:
        candidate = _dead_candidate_for_unit(
            module_name=module_name,
            local_name=local_name,
            node=node,
            filepath=filepath,
            suppression_index=suppression_index,
            protocol_class_qualnames=protocol_class_qualnames,
            non_runtime_decorator_aliases=non_runtime_decorator_aliases,
            pydantic_module_aliases=pydantic_module_aliases,
        )
        if candidate is not None:
            candidates.append(candidate)

    for class_qualname, class_node in collector.class_nodes:
        if class_qualname in protocol_class_qualnames:
            continue
        span = _node_line_span(class_node)
        if span is not None:
            start, end = span
            candidates.append(
                _build_dead_candidate(
                    module_name=module_name,
                    local_name=class_qualname,
                    node=class_node,
                    filepath=filepath,
                    kind="class",
                    suppression_index=suppression_index,
                    start_line=start,
                    end_line=end,
                )
            )

    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
            ),
        )
    )


def _collect_declaration_targets(
    *,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    source_tokens: tuple[tokenize.TokenInfo, ...] = (),
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
    include_inline_lines: bool = False,
) -> tuple[DeclarationTarget, ...]:
    declarations: list[DeclarationTarget] = []
    declaration_specs: list[
        tuple[str, ast.AST, Literal["function", "method", "class"]]
    ] = [
        (
            local_name,
            node,
            "method" if "." in local_name else "function",
        )
        for local_name, node in collector.units
    ]
    declaration_specs.extend(
        (class_qualname, class_node, "class")
        for class_qualname, class_node in collector.class_nodes
    )

    for qualname_suffix, node, kind in declaration_specs:
        start = int(getattr(node, "lineno", 0))
        end = int(getattr(node, "end_lineno", 0))
        if start > 0 and end > 0:
            declaration_end_line = (
                _declaration_end_line(
                    node,
                    source_tokens=source_tokens,
                    source_token_index=source_token_index,
                )
                if include_inline_lines
                else None
            )
            declarations.append(
                DeclarationTarget(
                    filepath=filepath,
                    qualname=f"{module_name}:{qualname_suffix}",
                    start_line=start,
                    end_line=end,
                    kind=kind,
                    declaration_end_line=declaration_end_line,
                )
            )

    return tuple(
        sorted(
            declarations,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.kind,
            ),
        )
    )


def _build_suppression_index_for_source(
    *,
    source: str,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
) -> Mapping[SuppressionTargetKey, tuple[str, ...]]:
    suppression_directives = extract_suppression_directives(source)
    if not suppression_directives:
        return {}

    needs_inline_binding = any(
        directive.binding == "inline" for directive in suppression_directives
    )
    source_tokens: tuple[tokenize.TokenInfo, ...] = ()
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None
    if needs_inline_binding:
        source_tokens = _source_tokens(source)
        if source_tokens:
            source_token_index = _build_declaration_token_index(source_tokens)

    declaration_targets = _collect_declaration_targets(
        filepath=filepath,
        module_name=module_name,
        collector=collector,
        source_tokens=source_tokens,
        source_token_index=source_token_index,
        include_inline_lines=needs_inline_binding,
    )
    suppression_bindings = bind_suppressions_to_declarations(
        directives=suppression_directives,
        declarations=declaration_targets,
    )
    return build_suppression_index(suppression_bindings)
