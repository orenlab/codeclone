# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import tokenize
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

from .. import qualnames as _qualnames
from ..models import DeadCandidate, ModuleDep
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
    protocol_symbol_aliases: set[str] = field(default_factory=lambda: {"Protocol"})
    protocol_module_aliases: set[str] = field(
        default_factory=lambda: set(_PROTOCOL_MODULE_NAMES)
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


def _dotted_expr_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        prefix = _dotted_expr_name(expr.value)
        if prefix is None:
            return None
        return f"{prefix}.{expr.attr}"
    return None


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
        for alias in node.names:
            if alias.name == "Protocol":
                state.protocol_symbol_aliases.add(alias.asname or alias.name)

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


def _is_non_runtime_candidate(node: _qualnames.FunctionNode) -> bool:
    for decorator in node.decorator_list:
        name = _dotted_expr_name(decorator)
        if name is None:
            continue
        terminal = name.rsplit(".", 1)[-1]
        if terminal in {"overload", "abstractmethod"}:
            return True
    return False


def _dead_candidate_kind(local_name: str) -> Literal["function", "method"]:
    return "method" if "." in local_name else "function"


def _should_skip_dead_candidate(
    local_name: str,
    node: _qualnames.FunctionNode,
    *,
    protocol_class_qualnames: set[str],
) -> bool:
    if _is_non_runtime_candidate(node):
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
) -> DeadCandidate | None:
    span = _node_line_span(node)
    if span is None:
        return None
    if _should_skip_dead_candidate(
        local_name,
        node,
        protocol_class_qualnames=protocol_class_qualnames,
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

    return frozenset(resolved)


class _ModuleWalkResult(NamedTuple):
    import_names: frozenset[str]
    module_deps: tuple[ModuleDep, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    protocol_symbol_aliases: frozenset[str]
    protocol_module_aliases: frozenset[str]


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
        )
        if candidate is not None:
            candidates.append(candidate)

    for class_qualname, class_node in collector.class_nodes:
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
