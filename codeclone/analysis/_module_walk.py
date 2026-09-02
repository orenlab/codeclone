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
    METHOD_DECORATOR_EVIDENCE_MARKERS,
    DeadCandidate,
    DependencyBinding,
    FunctionRelationshipFacts,
    ImportObservation,
    ModuleDep,
    ModuleRegistryHandle,
    RelationshipOriginLane,
    RelationshipRecord,
    ResolvedSourceIdentity,
    SemanticEvent,
)
from ..semantics.events import SemanticEventCollector
from .ast_helpers import is_type_checking_guard
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
_LocalLivenessRootReason = Literal["external_decorator"]
_MarkerAssignmentKind = Literal["call", "copy"]
# Canonical identities of the pluggy hook markers (liveness policy v2). A
# resolved ``@hookspec`` roots a declaration and a resolved ``@hookimpl``
# roots an implementation - two INDEPENDENT decorator roots, never a pair:
# a spec without an impl is a public extension contract, and an impl
# without a spec implements an external host's contract. The root fires
# only on the PROVEN marker binding - a module-scope assignment whose call
# resolves to one of these identities through the module's import bindings.
# The decorator NAME alone is never evidence.
_HOOK_MARKER_CANONICAL_SYMBOLS = frozenset(
    {"pluggy:HookimplMarker", "pluggy:HookspecMarker"}
)
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


def _source_module_key(source: ResolvedSourceIdentity) -> str:
    module = source.python_module
    return module.module if module is not None else source.file.path


def _node_is_lazy(node: ast.AST) -> bool:
    """Read the PEP 810 laziness marker exactly as the AST presents it.

    Interpreters below 3.15 never set the field; the wire decoder and a 3.15
    parser both surface it as a node attribute, so one read covers all three
    producers without version branching.
    """

    return bool(vars(node).get("is_lazy"))


def _edge_binding(
    *,
    runtime_reachable: bool,
    in_module_getattr: bool,
    in_callable: bool,
    is_lazy: bool,
) -> DependencyBinding:
    """Binding time by AST position — a closed decision table, no heuristics.

    | runtime | module ``__getattr__`` | callable body | lazy | binding           |
    |---------|------------------------|---------------|------|-------------------|
    | no      | *                      | *             | *    | type_checking     |
    | yes     | yes                    | *             | *    | deferred_getattr  |
    | yes     | no                     | yes           | *    | deferred_function |
    | yes     | no                     | no            | yes  | lazy_syntax       |
    | yes     | no                     | no            | no   | import_time       |

    Class bodies are deliberately NOT deferred: a class statement executes
    while the module is being imported, so its imports fire at import time.
    """

    if not runtime_reachable:
        return "type_checking"
    if in_module_getattr:
        return "deferred_getattr"
    if in_callable:
        return "deferred_function"
    if is_lazy:
        return "lazy_syntax"
    return "import_time"


def _classify_import_target(
    target: str,
    registry: ModuleRegistryHandle,
) -> Literal["analyzed", "known_internal_not_analyzed", "external"]:
    entry = registry.entries_by_module.get(target)
    if entry is not None:
        return entry.internality
    for prefix in registry.package_prefixes:
        if prefix.module != target:
            continue
        return (
            "analyzed"
            if any(
                registry.entries_by_path[path].analyzed
                for path in prefix.contributing_paths
            )
            else "known_internal_not_analyzed"
        )
    return "external"


def resolve_import_observation(
    source: ResolvedSourceIdentity,
    node: ast.ImportFrom,
    registry: ModuleRegistryHandle,
    *,
    binding: DependencyBinding = "import_time",
) -> ImportObservation:
    requested_names = tuple(sorted(alias.name for alias in node.names))
    requested_module = node.module
    is_lazy = _node_is_lazy(node)
    if node.level <= 0:
        target = requested_module or ""
        return ImportObservation(
            source=source,
            syntax_kind="from_import",
            level=0,
            requested_module=requested_module,
            requested_names=requested_names,
            resolution=_classify_import_target(target, registry),
            candidate_targets=(target,),
            resolved_target=target,
            binding=binding,
            is_lazy=is_lazy,
        )

    module = source.python_module
    package_parts = (
        module.package.split(".") if module is not None and module.package else []
    )
    parents_to_strip = node.level - 1
    if module is None or not package_parts or parents_to_strip >= len(package_parts):
        return ImportObservation(
            source=source,
            syntax_kind="from_import",
            level=node.level,
            requested_module=requested_module,
            requested_names=requested_names,
            resolution="unresolved_relative",
            candidate_targets=(),
            resolved_target=None,
            binding=binding,
            is_lazy=is_lazy,
        )

    base_parts = package_parts[: len(package_parts) - parents_to_strip]
    target = (
        ".".join((*base_parts, requested_module))
        if requested_module
        else ".".join(base_parts)
    )
    return ImportObservation(
        source=source,
        syntax_kind="from_import",
        level=node.level,
        requested_module=requested_module,
        requested_names=requested_names,
        resolution=_classify_import_target(target, registry),
        candidate_targets=(target,),
        resolved_target=target,
        binding=binding,
        is_lazy=is_lazy,
    )


def _import_from_observations(
    source: ResolvedSourceIdentity,
    node: ast.ImportFrom,
    registry: ModuleRegistryHandle,
    *,
    binding: DependencyBinding = "import_time",
) -> tuple[ImportObservation, ...]:
    primary = resolve_import_observation(source, node, registry, binding=binding)
    target = primary.resolved_target
    if target is None or node.module is not None:
        return (primary,)
    expansions: list[ImportObservation] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        candidate = f"{target}.{alias.name}"
        resolution = _classify_import_target(candidate, registry)
        if resolution == "external":
            continue
        expansions.append(
            ImportObservation(
                source=source,
                syntax_kind="from_import",
                level=node.level,
                requested_module=None,
                requested_names=(alias.name,),
                resolution=resolution,
                candidate_targets=(candidate,),
                resolved_target=candidate,
                inventory_expansion=True,
                binding=primary.binding,
                is_lazy=primary.is_lazy,
            )
        )
    return (primary, *expansions)


@dataclass(slots=True)
class _ModuleWalkState:
    import_names: set[str] = field(default_factory=set)
    # Every name an import statement BINDS in this module's namespace:
    # `import a.b` -> "a", `import a.b as c` -> "c", `from m import x as y`
    # -> "y". Unlike import_names (top-level module names) and
    # imported_symbol_bindings (resolution- and lane-gated), this set is
    # collected unconditionally, so the CBO imported-domain lane means the
    # same thing in every file. See codeclone/metrics/coupling.py.
    imported_binding_names: set[str] = field(default_factory=set)
    # Binding name -> the qualname its import resolves to ("pkg.mod:Name"),
    # and binding name -> the module a dotted access off that name reads from.
    # Both feed the resolved-instantiation CBO lane, and both are collected
    # unconditionally for the same reason imported_binding_names is: a metric
    # must not depend on which lane the file belongs to.
    # imported_symbol_bindings below is reference tracking and stays gated.
    binding_symbol_targets: dict[str, str] = field(default_factory=dict)
    binding_module_targets: dict[str, str] = field(default_factory=dict)
    deps: list[ModuleDep] = field(default_factory=list)
    referenced_names: set[str] = field(default_factory=set)
    imported_symbol_bindings: dict[str, set[str]] = field(default_factory=dict)
    # Resolved targets of ``from <target> import *``. A wildcard alias names no
    # symbol, so it writes nothing into imported_symbol_bindings above and the
    # binding is lost; the module it reads from is the one thing about the
    # import that IS statically known, and this set keeps it. Gated exactly
    # like imported_symbol_bindings, so a wildcard is admitted wherever the
    # named import it stands for would be.
    wildcard_import_targets: set[str] = field(default_factory=set)
    imported_module_aliases: dict[str, str] = field(default_factory=dict)
    external_symbol_aliases: set[str] = field(default_factory=set)
    external_module_aliases: set[str] = field(default_factory=set)
    liveness_root_reasons: dict[str, _LocalLivenessRootReason] = field(
        default_factory=dict
    )
    name_nodes: list[ast.Name] = field(default_factory=list)
    attr_nodes: list[ast.Attribute] = field(default_factory=list)
    # Resolved ``module:symbol`` targets of PEP 484 explicit re-exports
    # (``from x import y as y``) found at module scope in a runtime-reachable
    # branch of a production file. One of the two independent life proofs for
    # an imported symbol under liveness policy v2; static ``__all__``
    # membership remains the other, stronger explicit contract.
    explicit_reexport_qualnames: set[str] = field(default_factory=set)
    # Module-scope ``name = <call>`` / ``name = other_name`` assignments,
    # recorded raw during the walk and resolved after it, so a marker bound
    # before its import statement is judged against the complete binding maps.
    hook_marker_assignments: list[tuple[str, _MarkerAssignmentKind, str]] = field(
        default_factory=list
    )
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
    observation: ImportObservation,
    line: int,
    state: _ModuleWalkState,
) -> None:
    state.deps.append(
        ModuleDep(
            source=_source_module_key(observation.source),
            target=observation.resolved_target or "",
            import_type=observation.syntax_kind,
            line=line,
            resolution=observation.resolution,
            inventory_expansion=observation.inventory_expansion,
            level=observation.level,
            requested_module=observation.requested_module,
            requested_names=observation.requested_names,
            candidate_targets=observation.candidate_targets,
            mechanism=observation.mechanism,
            binding=observation.binding,
            is_lazy=observation.is_lazy,
        )
    )


def _dynamic_event_binding(event: SemanticEvent) -> DependencyBinding:
    """Binding time of a dynamic load, read from the event's recorded scope.

    The event layer already stamped ``security.location_scope=`` as a const
    input at detection time. A load in a callable body binds when that
    callable is called; module- and class-scope loads execute while the
    module is being imported. Consumed, never re-derived.
    """

    for fact in event.inputs:
        if fact.ref == "security.location_scope=callable":
            return "deferred_function"
    return "import_time"


def _append_dynamic_load_deps(
    *,
    events: tuple[SemanticEvent, ...],
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    state: _ModuleWalkState,
) -> None:
    """Project dynamic-load events into dependency facts.

    Detection stays upstream in the semantics event layer; this only consumes
    what the detector already saw, and resolves literals through the same
    classifier as static imports.
    """

    for event in events:
        argument = event.dynamic_load
        if argument is None:
            continue
        target = argument.module
        _append_module_dep(
            observation=ImportObservation(
                source=source,
                syntax_kind="import",
                level=0,
                requested_module=target,
                requested_names=(),
                resolution=(
                    "unresolved_dynamic"
                    if target is None
                    else _classify_import_target(target, registry)
                ),
                candidate_targets=() if target is None else (target,),
                resolved_target=target,
                mechanism="dynamic",
                binding=_dynamic_event_binding(event),
            ),
            line=event.location[1],
            state=state,
        )


def _collect_import_node(
    *,
    node: ast.Import,
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
    binding: DependencyBinding = "import_time",
) -> None:
    line = int(getattr(node, "lineno", 0))
    is_lazy = _node_is_lazy(node)
    for alias in node.names:
        alias_name = alias.asname or alias.name.split(".", 1)[0]
        state.import_names.add(alias_name)
        state.imported_binding_names.add(alias_name)
        # `import a.b as c` binds the whole path to `c`; plain `import a.b`
        # binds only `a`, which is then the module a dotted access reads from.
        state.binding_module_targets[alias_name] = (
            alias.name if alias.asname else alias.name.split(".", 1)[0]
        )
        observation = ImportObservation(
            source=source,
            syntax_kind="import",
            level=0,
            requested_module=alias.name,
            requested_names=(),
            resolution=_classify_import_target(alias.name, registry),
            candidate_targets=(alias.name,),
            resolved_target=alias.name,
            binding=binding,
            is_lazy=is_lazy,
        )
        _append_module_dep(
            observation=observation,
            line=line,
            state=state,
        )
        if observation.resolution == "external":
            state.external_module_aliases.add(alias_name)
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
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
    runtime_reachable: bool = True,
    module_scope: bool = True,
    binding: DependencyBinding = "import_time",
) -> None:
    observations = _import_from_observations(source, node, registry, binding=binding)
    primary_observation = observations[0]
    primary_target = primary_observation.resolved_target
    # Unconditional: a `from` import binds its alias names whether or not the
    # module resolves and whichever lane the file belongs to.
    state.imported_binding_names.update(
        alias.asname or alias.name for alias in node.names if alias.name != "*"
    )
    if primary_target:
        # One import binds one name, but that name may denote either a symbol
        # of the target module or a submodule of it. Both readings are
        # recorded; only the class index decides which one, if either, names a
        # class.
        for alias in node.names:
            if alias.name != "*":
                alias_name = alias.asname or alias.name
                state.binding_symbol_targets[alias_name] = (
                    f"{primary_target}:{alias.name}"
                )
                state.binding_module_targets[alias_name] = (
                    f"{primary_target}.{alias.name}"
                )
    for observation in observations:
        target = observation.resolved_target
        if target:
            state.import_names.add(target.partition(".")[0])
        _append_module_dep(
            observation=observation,
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

    if primary_observation.resolution == "external":
        state.external_symbol_aliases.update(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )

    if not collect_referenced_names or not primary_target:
        return

    for alias in node.names:
        if alias.name == "*":
            # The one binding fact a wildcard carries: the module it reads
            # from. Which names it binds is decided later, by the ``__all__``
            # of the module doing the importing - the only static export
            # evidence available without leaving this file.
            state.wildcard_import_targets.add(primary_target)
            continue
        alias_name = alias.asname or alias.name
        state.imported_symbol_bindings.setdefault(alias_name, set()).add(
            f"{primary_target}:{alias.name}"
        )
        # PEP 484 explicit re-export: the ``as``-SAME-name spelling is a life
        # proof for the resolved target on its own. A renaming import is not;
        # a ``TYPE_CHECKING``-guarded or non-module-scope import never fires
        # this proof. Relative imports are already resolved to exact identity
        # by ``resolve_import_observation`` or ``primary_target`` is None and
        # the early return above kept this proof out of reach.
        if runtime_reachable and module_scope and alias.asname == alias.name:
            state.explicit_reexport_qualnames.add(f"{primary_target}:{alias.name}")


def _collect_hook_marker_assignment_node(
    node: ast.Assign | ast.AnnAssign,
    state: _ModuleWalkState,
) -> None:
    """Record a module-scope assignment that may bind a hook marker.

    Raw collection only: ``name = <dotted>(...)`` and ``name = other_name``
    shapes are stored with their dotted value names, and
    ``_resolve_hook_marker_aliases`` judges them against the complete import
    binding maps once the walk is done.
    """
    match node:
        case ast.Assign(targets=targets, value=ast.Call(func=func)):
            bound_names = [
                target.id for target in targets if isinstance(target, ast.Name)
            ]
            assignment_kind: _MarkerAssignmentKind = "call"
            dotted_name = _dotted_expr_name(func)
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call(func=func)):
            bound_names = [name]
            assignment_kind = "call"
            dotted_name = _dotted_expr_name(func)
        case ast.Assign(targets=targets, value=ast.Name(id=source_name)):
            bound_names = [
                target.id for target in targets if isinstance(target, ast.Name)
            ]
            assignment_kind = "copy"
            dotted_name = source_name
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.Name(id=source_name)):
            bound_names = [name]
            assignment_kind = "copy"
            dotted_name = source_name
        case _:
            return
    if dotted_name is None:
        return
    for bound_name in bound_names:
        state.hook_marker_assignments.append((bound_name, assignment_kind, dotted_name))


def _binding_symbol_identity(
    dotted_name: str,
    state: _ModuleWalkState,
) -> str | None:
    """Canonical ``module:symbol`` identity a module-level name resolves to."""
    if "." not in dotted_name:
        return state.binding_symbol_targets.get(dotted_name)
    root_name, _, attribute_path = dotted_name.partition(".")
    module_target = state.binding_module_targets.get(root_name)
    if module_target is None:
        return None
    return f"{module_target}:{attribute_path}"


def _resolve_hook_marker_aliases(state: _ModuleWalkState) -> frozenset[str]:
    """Module-level names PROVEN to bind a pluggy hook marker.

    A name is proven by a recorded call-assignment whose callee resolves to a
    canonical marker identity, or by a plain name-copy of an already-proven
    alias (bounded fixpoint, order-independent). A user's own decorator that
    merely SHARES the ``hookspec`` / ``hookimpl`` name never resolves here.
    """
    aliases: set[str] = set()
    copies: list[tuple[str, str]] = []
    for bound_name, assignment_kind, dotted_name in state.hook_marker_assignments:
        if assignment_kind == "call":
            if _binding_symbol_identity(dotted_name, state) in (
                _HOOK_MARKER_CANONICAL_SYMBOLS
            ):
                aliases.add(bound_name)
        else:
            copies.append((bound_name, dotted_name))
    for _round in range(len(copies)):
        changed = False
        for bound_name, source_name in copies:
            if source_name in aliases and bound_name not in aliases:
                aliases.add(bound_name)
                changed = True
        if not changed:
            break
    return frozenset(aliases)


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
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
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
            target = resolve_import_observation(source, node, registry).resolved_target
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


def _accumulate_caller_binding_from_scope_node(
    scope_node: ast.AST,
    *,
    bound_names: set[str],
    global_names: set[str],
    nonlocal_names: set[str],
) -> None:
    if isinstance(scope_node, ast.Name) and isinstance(
        scope_node.ctx, ast.Store | ast.Del
    ):
        bound_names.add(scope_node.id)
    elif isinstance(scope_node, ast.Import):
        bound_names.update(
            alias.asname or alias.name.split(".", 1)[0] for alias in scope_node.names
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


def _walk_relationship_function_scope(
    node: _qualnames.FunctionNode,
) -> tuple[frozenset[str], tuple[ast.AST, ...]]:
    """Single DFS over a function body for caller bindings and scope nodes."""
    bound_names = _function_parameter_names(node)
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()
    scope_nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(reversed(node.body))
    while stack:
        scope_node = stack.pop()
        scope_nodes.append(scope_node)
        _accumulate_caller_binding_from_scope_node(
            scope_node,
            bound_names=bound_names,
            global_names=global_names,
            nonlocal_names=nonlocal_names,
        )
        if isinstance(
            scope_node,
            ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
        ):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(scope_node))))
    bound_names.difference_update(global_names)
    bound_names.difference_update(nonlocal_names)
    return frozenset(sorted(bound_names)), tuple(scope_nodes)


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
        if node.id in top_level_class_names:
            return f"{module_name}:{node.id}", "same_module_class"
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
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    filepath: str,
    collector: _qualnames.QualnameCollector,
    origin_lane: RelationshipOriginLane,
) -> tuple[FunctionRelationshipFacts, ...]:
    imports = _collect_relationship_import_index(
        tree=tree,
        source=source,
        registry=registry,
    )
    module_name = _source_module_key(source)
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
        caller_bindings, scope_nodes = _walk_relationship_function_scope(function_node)
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


def _is_typing_overload_stub(
    node: _qualnames.FunctionNode,
    *,
    overload_aliases: frozenset[str],
) -> bool:
    """True for a `@overload` declaration, which has no implementation body.

    Every overload of one function shares that function's qualname, so a stub
    is not a second function — treating it as one makes the qualname ambiguous
    downstream.
    """

    for decorator in node.decorator_list:
        name = _decorator_expr_name(decorator)
        if name is None:
            continue
        if name in overload_aliases or name.rsplit(".", 1)[-1] == "overload":
            return True
    return False


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
        # The wildcard edge names the module, ``__all__`` names the symbol:
        # together they are a statically resolvable export binding, which is
        # what ``from x import *`` otherwise throws away. Resolution is a
        # plain product because the walk cannot know which of several
        # wildcards bound the name; a product with no matching declaration is
        # inert, since no candidate anywhere carries that qualname. Kept
        # unconditional rather than a fallback: a wildcard genuinely can
        # shadow an earlier named import, and over-resolving costs a missed
        # finding while under-resolving asserts that live API is dead.
        for wildcard_target in state.wildcard_import_targets:
            resolved.add(f"{wildcard_target}:{exported_name}")
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

    # Liveness policy v2: the PEP 484 explicit re-export proof, independent
    # of ``__all__``. Targets were resolved to exact identity at collection
    # time, so this is a plain union like the export chain above.
    resolved.update(state.explicit_reexport_qualnames)

    local_top_level_names = frozenset(
        {
            *top_level_function_by_name,
            *top_level_class_by_name,
        }
    )
    external_decorator_roots = _collect_external_decorator_root_reasons(
        module_name=module_name,
        collector=collector,
        state=state,
        local_top_level_names=local_top_level_names,
    )
    resolved.update(external_decorator_roots)
    state.liveness_root_reasons.update(external_decorator_roots)

    return frozenset(resolved)


def _resolve_star_import_bound_qualnames(
    *,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    state: _ModuleWalkState,
) -> frozenset[str]:
    """The locally defined names ``from <this module> import *`` binds.

    The language rule, not a heuristic: a module that declares ``__all__``
    binds exactly the names it lists, and a module that does not binds every
    top-level name that does not start with an underscore. Only local
    definitions are resolved, because the one consumer asks whether a class
    DEFINED here reaches a namespace that stars this module.

    An ``__all__`` the walk could not read statically leaves ``exported_names``
    empty and falls to the public-name arm. That is the pre-existing reading,
    and it is the conservative one: under-binding here would re-assert that
    live public API is dead, which is the failure this fact exists to prevent.

    Known limitation, with its direction: ``exported_names`` is a bare set, so
    an ABSENT ``__all__``, an explicitly empty ``__all__ = []`` and one built
    dynamically are indistinguishable here - all three take the public-name
    arm. ``__all__ = []`` binds nothing under ``import *``, so that one case is
    OVER-bound: it can leave a member live that the star does not carry, never
    the reverse. Telling the three apart needs a tri-state on the walk state,
    which is a per-symbol cache-wire fact and a separate decision.
    """

    top_level_functions = {
        local_name for local_name, _node in collector.units if "." not in local_name
    }
    top_level_classes = {
        qualname for qualname, _node in collector.class_nodes if "." not in qualname
    }
    local_top_level = top_level_functions | top_level_classes
    bound = (
        {name for name in state.exported_names if name in local_top_level}
        if state.exported_names
        else {name for name in local_top_level if not name.startswith("_")}
    )
    return frozenset(f"{module_name}:{name}" for name in bound)


def _collect_external_decorator_root_reasons(
    *,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    state: _ModuleWalkState,
    local_top_level_names: frozenset[str],
) -> dict[str, _LocalLivenessRootReason]:
    hook_marker_aliases = _resolve_hook_marker_aliases(state)
    overload_aliases = frozenset(state.non_runtime_decorator_aliases)
    return {
        f"{module_name}:{local_name}": "external_decorator"
        # An ``@overload`` stub is a DECLARATION of this symbol, not a use of
        # it: every stub shares the implementation's qualname, so admitting one
        # lets a symbol stand as its own external evidence. ``typing.overload``
        # resolves through an external module alias and is otherwise
        # indistinguishable from a framework registration, which is how a
        # method whose only real evidence was an ordinary call site came to be
        # recorded as live because something external decorated it.
        for local_name, function_node in collector.units
        if not _is_typing_overload_stub(
            function_node,
            overload_aliases=overload_aliases,
        )
        and (
            _has_external_decorator(
                function_node,
                external_symbol_aliases=state.external_symbol_aliases,
                external_module_aliases=state.external_module_aliases,
                local_top_level_names=local_top_level_names,
            )
            or _has_hook_marker_decorator(function_node, hook_marker_aliases)
        )
    }


def _class_base_expr_name(node: ast.expr) -> str | None:
    """Dotted name of a base expression, unwrapping generic subscripts.

    ``TypeDecorator[object]`` and ``Generic[T]`` name the same base as their
    unsubscripted form, so the subscript is peeled before resolution.
    """
    if isinstance(node, ast.Subscript):
        return _class_base_expr_name(node.value)
    return _decorator_expr_name(node)


def _collect_class_base_facts(
    *,
    collector: _qualnames.QualnameCollector,
    state: _ModuleWalkState,
    local_top_level_names: frozenset[str],
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], frozenset[str]]:
    """Per-class base names, plus the classes whose base escapes the root.

    Keyed by the module-LOCAL class qualname; the caller owns the module
    prefix. Returns primitives so the facts can ride on ``ClassMetrics``
    without introducing a type edge on any of its carriers.

    Classes without bases are omitted: they have nothing to resolve, and their
    absence is not ambiguous. A base is unresolved-external when its root name
    binds to an import the registry could not place inside the analysis root -
    the same opacity doctrine as the external-decorator root rule.
    """
    base_names_by_class: list[tuple[str, tuple[str, ...]]] = []
    unresolved_external: set[str] = set()
    for class_qualname, class_node in collector.class_nodes:
        base_names: set[str] = set()
        has_unresolved_external_base = False
        for base in class_node.bases:
            base_name = _class_base_expr_name(base)
            if base_name is None:
                continue
            base_names.add(base_name)
            root_name = base_name.partition(".")[0]
            if root_name in local_top_level_names:
                continue
            if (
                root_name in state.external_symbol_aliases
                or root_name in state.external_module_aliases
            ):
                has_unresolved_external_base = True
        if not base_names:
            continue
        base_names_by_class.append((class_qualname, tuple(sorted(base_names))))
        if has_unresolved_external_base:
            unresolved_external.add(class_qualname)
    return (
        tuple(sorted(base_names_by_class, key=lambda item: item[0])),
        frozenset(unresolved_external),
    )


def _collect_decorator_evidenced_methods(
    *,
    collector: _qualnames.QualnameCollector,
) -> frozenset[str]:
    """Row 2 of the rule-3 table: explicit dispatch contracts on the method.

    Only membership matters downstream - the decision table asks whether an
    explicit contract exists, never which marker spelled it - so the marker
    names are not carried past this point. Keyed by module-LOCAL qualname.
    """
    return frozenset(
        local_name
        for local_name, function_node in collector.units
        if "." in local_name
        and any(
            _decorator_evidence_marker(decorator) is not None
            for decorator in function_node.decorator_list
        )
    )


def _decorator_evidence_marker(decorator: ast.expr) -> str | None:
    name = _decorator_expr_name(decorator)
    if name is None:
        return None
    leaf_name = name.rpartition(".")[2]
    if leaf_name in METHOD_DECORATOR_EVIDENCE_MARKERS:
        return leaf_name
    return None


def _has_hook_marker_decorator(
    node: _qualnames.FunctionNode,
    hook_marker_aliases: frozenset[str],
) -> bool:
    """Whether a decorator expression IS a proven hook marker alias.

    Exact-name equality after unwrapping a decorator call, so ``@hookspec``
    and ``@hookimpl(tryfirst=True)`` both fire while an attribute path rooted
    at a marker alias does not - the proof covers the marker object itself,
    nothing reached through it.
    """
    if not hook_marker_aliases:
        return False
    return any(
        _decorator_expr_name(decorator) in hook_marker_aliases
        for decorator in node.decorator_list
    )


def _has_external_decorator(
    node: _qualnames.FunctionNode,
    *,
    external_symbol_aliases: set[str],
    external_module_aliases: set[str],
    local_top_level_names: frozenset[str],
) -> bool:
    for decorator in node.decorator_list:
        name = _decorator_expr_name(decorator)
        if name is None:
            continue
        root_name = name.partition(".")[0]
        if root_name in local_top_level_names:
            continue
        if root_name in external_symbol_aliases or root_name in external_module_aliases:
            return True
    return False


class _ModuleWalkResult(NamedTuple):
    import_names: frozenset[str]
    imported_binding_names: frozenset[str]
    # Resolution inputs for the instantiation CBO lane; see the state fields.
    binding_symbol_targets: dict[str, str]
    binding_module_targets: dict[str, str]
    module_deps: tuple[ModuleDep, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    liveness_root_reasons: tuple[tuple[str, _LocalLivenessRootReason], ...]
    #: What ``from <this module> import *`` binds among the module's own
    #: definitions. A binding fact, independent of whether anything references
    #: the name: the wildcard re-export rule needs to know what an edge CARRIES
    #: before it can ask what the project holds live.
    star_import_bound_qualnames: frozenset[str]
    # Rule-3 facts, keyed by module-LOCAL qualname; units.py adds the module
    # prefix when it attaches them to the owning ClassMetrics.
    class_base_names: tuple[tuple[str, tuple[str, ...]], ...]
    unresolved_external_base_classes: frozenset[str]
    decorator_evidenced_methods: frozenset[str]
    protocol_symbol_aliases: frozenset[str]
    protocol_module_aliases: frozenset[str]
    non_runtime_decorator_aliases: frozenset[str]
    pydantic_module_aliases: frozenset[str]
    cohesion_ignored_decorator_aliases: frozenset[str]
    semantic_events: tuple[SemanticEvent, ...]


def _collect_module_walk_node(
    *,
    node: ast.AST,
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
    runtime_reachable: bool = True,
    module_scope: bool = True,
    in_module_getattr: bool = False,
    in_callable: bool = False,
) -> None:
    if isinstance(node, ast.Import | ast.ImportFrom):
        binding = _edge_binding(
            runtime_reachable=runtime_reachable,
            in_module_getattr=in_module_getattr,
            in_callable=in_callable,
            is_lazy=_node_is_lazy(node),
        )
    if isinstance(node, ast.Import):
        _collect_import_node(
            node=node,
            source=source,
            registry=registry,
            state=state,
            collect_referenced_names=collect_referenced_names,
            binding=binding,
        )
    elif isinstance(node, ast.ImportFrom):
        _collect_import_from_node(
            node=node,
            source=source,
            registry=registry,
            state=state,
            collect_referenced_names=collect_referenced_names,
            runtime_reachable=runtime_reachable,
            module_scope=module_scope,
            binding=binding,
        )
    elif collect_referenced_names:
        if (
            runtime_reachable
            and module_scope
            and isinstance(node, ast.Assign | ast.AnnAssign)
        ):
            _collect_hook_marker_assignment_node(node, state)
        _collect_load_reference_node(node=node, state=state)


def _walk_module_tree(
    *,
    node: ast.AST,
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    state: _ModuleWalkState,
    event_collector: SemanticEventCollector,
    collect_referenced_names: bool,
    scope: tuple[str, ...] = (),
    callable_depth: int = 0,
    class_depth: int = 0,
    runtime_enabled: bool = True,
    guards: tuple[str, ...] = (),
    in_module_getattr: bool = False,
) -> None:
    _collect_module_walk_node(
        node=node,
        source=source,
        registry=registry,
        state=state,
        collect_referenced_names=collect_referenced_names,
        runtime_reachable=runtime_enabled,
        module_scope=callable_depth == 0 and class_depth == 0,
        in_module_getattr=in_module_getattr,
        in_callable=callable_depth > 0,
    )
    if runtime_enabled:
        event_collector.observe(
            node,
            scope=scope,
            callable_depth=callable_depth,
            class_depth=class_depth,
            guards=guards,
        )

    child_scope = scope
    child_callable_depth = callable_depth
    child_class_depth = class_depth
    child_in_module_getattr = in_module_getattr
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        child_scope = (*scope, node.name)
        # The PEP 562 hook is exactly the module-scope function named
        # ``__getattr__``: its body binds on attribute miss. An instance
        # ``__getattr__`` inside a class is an ordinary deferred callable.
        if callable_depth == 0 and class_depth == 0 and node.name == "__getattr__":
            child_in_module_getattr = True
        child_callable_depth += 1
    elif isinstance(node, ast.ClassDef):
        child_scope = (*scope, node.name)
        child_class_depth += 1

    if isinstance(node, ast.If):
        _walk_module_tree(
            node=node.test,
            source=source,
            registry=registry,
            state=state,
            event_collector=event_collector,
            collect_referenced_names=collect_referenced_names,
            scope=child_scope,
            callable_depth=child_callable_depth,
            class_depth=child_class_depth,
            runtime_enabled=False
            if is_type_checking_guard(node.test)
            else runtime_enabled,
            guards=guards,
            in_module_getattr=child_in_module_getattr,
        )
        type_checking_only = is_type_checking_guard(node.test)
        branch_guard = f"if@{int(getattr(node, 'lineno', 0))}"
        for child in node.body:
            _walk_module_tree(
                node=child,
                source=source,
                registry=registry,
                state=state,
                event_collector=event_collector,
                collect_referenced_names=collect_referenced_names,
                scope=child_scope,
                callable_depth=child_callable_depth,
                class_depth=child_class_depth,
                runtime_enabled=runtime_enabled and not type_checking_only,
                guards=(*guards, f"{branch_guard}:true"),
                in_module_getattr=child_in_module_getattr,
            )
        for child in node.orelse:
            _walk_module_tree(
                node=child,
                source=source,
                registry=registry,
                state=state,
                event_collector=event_collector,
                collect_referenced_names=collect_referenced_names,
                scope=child_scope,
                callable_depth=child_callable_depth,
                class_depth=child_class_depth,
                runtime_enabled=runtime_enabled,
                guards=(*guards, f"{branch_guard}:false"),
                in_module_getattr=child_in_module_getattr,
            )
        return

    for nested_node in ast.iter_child_nodes(node):
        _walk_module_tree(
            node=nested_node,
            source=source,
            registry=registry,
            state=state,
            event_collector=event_collector,
            collect_referenced_names=collect_referenced_names,
            scope=child_scope,
            callable_depth=child_callable_depth,
            class_depth=child_class_depth,
            runtime_enabled=runtime_enabled,
            guards=guards,
            in_module_getattr=child_in_module_getattr,
        )


def _collect_module_walk_data(
    *,
    tree: ast.AST,
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    collector: _qualnames.QualnameCollector,
    collect_referenced_names: bool,
) -> _ModuleWalkResult:
    """Single ast.walk that collects imports, deps, names, qualnames & protocol aliases.

    Reduces the hot path to one tree walk plus one local qualname resolution phase.
    """
    state = _ModuleWalkState()
    module_name = _source_module_key(source)
    event_collector = SemanticEventCollector(
        module_name=module_name,
        filepath=source.file.path,
        top_level_class_names=frozenset(
            qualname for qualname, _node in collector.class_nodes if "." not in qualname
        ),
    )
    _collect_module_all_exports(tree, state)
    _walk_module_tree(
        node=tree,
        source=source,
        registry=registry,
        state=state,
        event_collector=event_collector,
        collect_referenced_names=collect_referenced_names,
    )
    if collect_referenced_names:
        state.referenced_names.update(_collect_dynamic_getattr_names(tree))
    _append_dynamic_load_deps(
        events=event_collector.events,
        source=source,
        registry=registry,
        state=state,
    )

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

    class_base_names, unresolved_external_base_classes = _collect_class_base_facts(
        collector=collector,
        state=state,
        local_top_level_names=frozenset(
            {
                *(name for name, _node in collector.units if "." not in name),
                *(name for name, _node in collector.class_nodes if "." not in name),
            }
        ),
    )

    return _ModuleWalkResult(
        import_names=frozenset(state.import_names),
        imported_binding_names=frozenset(state.imported_binding_names),
        binding_symbol_targets=dict(state.binding_symbol_targets),
        binding_module_targets=dict(state.binding_module_targets),
        module_deps=deps_sorted,
        referenced_names=frozenset(state.referenced_names),
        referenced_qualnames=resolved,
        liveness_root_reasons=tuple(sorted(state.liveness_root_reasons.items())),
        star_import_bound_qualnames=_resolve_star_import_bound_qualnames(
            module_name=module_name,
            collector=collector,
            state=state,
        ),
        class_base_names=class_base_names,
        unresolved_external_base_classes=unresolved_external_base_classes,
        decorator_evidenced_methods=_collect_decorator_evidenced_methods(
            collector=collector,
        ),
        protocol_symbol_aliases=frozenset(state.protocol_symbol_aliases),
        protocol_module_aliases=frozenset(state.protocol_module_aliases),
        non_runtime_decorator_aliases=frozenset(state.non_runtime_decorator_aliases),
        pydantic_module_aliases=frozenset(state.pydantic_module_aliases),
        cohesion_ignored_decorator_aliases=frozenset(
            state.cohesion_ignored_decorator_aliases
        ),
        semantic_events=event_collector.events,
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
