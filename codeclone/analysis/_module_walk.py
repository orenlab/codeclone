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
from typing import TYPE_CHECKING, Final, Literal, NamedTuple, TypeGuard

from .. import qualnames as _qualnames
from ..models import (
    LIVENESS_EXTERNAL_DECORATOR,
    METHOD_DECORATOR_EVIDENCE_MARKERS,
    RESOLUTION_AMBIGUOUS_IMPORT,
    RESOLUTION_IMPORTED_MODULE_ATTRIBUTE,
    RESOLUTION_IMPORTED_SYMBOL,
    RESOLUTION_LOCAL_SHADOWING,
    RESOLUTION_SAME_MODULE_CLASS,
    RESOLUTION_SAME_MODULE_CLASS_METHOD,
    RESOLUTION_SAME_MODULE_FUNCTION,
    RESOLUTION_SELF_OR_CLS_METHOD,
    RESOLUTION_UNRESOLVED_DYNAMIC,
    RESOLUTION_UNRESOLVED_NAME,
    DeadCandidate,
    DependencyBinding,
    FunctionRelationshipFacts,
    ImportObservation,
    ModuleDep,
    ModuleRegistryHandle,
    NestedDefinition,
    NestedDefinitionKind,
    RelationshipOriginLane,
    RelationshipRecord,
    ResolvedSourceIdentity,
    SemanticEvent,
    emit_live_root_reason,
    escape_witness,
    validate_resolution_rule,
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
    from collections.abc import Mapping, Sequence

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


def _from_import_module_bindings(
    *,
    node: ast.ImportFrom,
    resolved_target: str,
    registry: ModuleRegistryHandle,
) -> tuple[tuple[str, str], ...]:
    """The names one ``from`` import binds to a MODULE, resolved once for all.

    ``from pkg import _mod as alias`` and ``import pkg._mod as alias`` are the
    same binding written two ways: ``alias`` denotes the module, and
    ``alias.name`` reads a member of it. Only the second spelling says so
    syntactically, so the module reading of a ``from`` import is admitted
    exactly when the registry knows ``<target>.<name>`` as a module. Without
    that gate ``from pkg import helper`` would manufacture a member of a
    module named ``pkg.helper`` that does not exist, and a resolver that
    INVENTS a reference is worse than one that loses it: it revives symbols
    nothing binds, silently and without a name to blame.

    Every reference-resolving consumer calls this and gets the same answer, so
    the dialect is a property of the binding and never of the consumer's role.
    The symbol reading of the same import is untouched: ``pkg`` really does
    bind the name ``_mod``, and both readings are recorded, exactly as
    ``_collect_import_from_node`` already does for the coupling lane.
    """

    bindings: list[tuple[str, str]] = []
    for alias in node.names:
        submodule = f"{resolved_target}.{alias.name}"
        # A wildcard binds no name at all, and a target the registry does not
        # know as a module is an ordinary imported symbol - one refusal, two
        # ways of not being a module reading.
        if (
            alias.name == "*"
            or _classify_import_target(submodule, registry) == "external"
        ):
            continue
        bindings.append((alias.asname or alias.name, submodule))
    return tuple(bindings)


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
    # Liveness policy v5: the names an import binds whose loads the lexical
    # pass may SETTLE - a ``from`` import the registry placed inside the
    # analysis root (the imported-symbol lane then answers for the load), or
    # any ``import`` statement (the name denotes a module object, never a
    # definition). A ``from`` import that resolved external, or not at all,
    # is deliberately absent: the registry calls a script-style sibling
    # module external too, and a load bound by such an import must stay a
    # bare-name signal rather than be settled into silence.
    internal_import_aliases: set[str] = field(default_factory=set)
    liveness_root_reasons: dict[str, _LocalLivenessRootReason] = field(
        default_factory=dict
    )
    name_nodes: list[ast.Name] = field(default_factory=list)
    attr_nodes: list[ast.Attribute] = field(default_factory=list)
    # Resolved ``module:symbol`` targets of PEP 484 explicit re-exports
    # (``from x import y as y``) found at module scope in a runtime-reachable
    # branch of a production file. The one declaration-shaped life proof left
    # under liveness policy v4: an ``__all__`` entry is no longer one (it
    # binds a name for ``import *`` and declares an export; it uses nothing),
    # and this spelling stays a life proof only until its own ruling.
    explicit_reexport_qualnames: set[str] = field(default_factory=set)
    # Module-scope ``name = <call>`` / ``name = other_name`` assignments,
    # recorded raw during the walk and resolved after it, so a marker bound
    # before its import statement is judged against the complete binding maps.
    hook_marker_assignments: list[tuple[str, _MarkerAssignmentKind, str]] = field(
        default_factory=list
    )
    # The names this module's static ``__all__`` lists. A declaration, read
    # twice and never as a reference: the star-binding rule narrows what
    # ``from <this module> import *`` carries to these, and the exposure owner
    # reads them off the wire as ``declared_exports`` to tell a public plain
    # module's re-export (an import it lists) from an implementation detail,
    # and to name what a module-level ``__getattr__`` serves.
    exported_names: set[str] = field(default_factory=set)
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
        state.internal_import_aliases.add(alias_name)
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


def _collect_module_all_exports(tree: ast.AST, state: _ModuleWalkState) -> None:
    if not isinstance(tree, ast.Module):
        return
    for statement in tree.body:
        _collect_all_export_node(statement, state)


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
    elif primary_target:
        state.internal_import_aliases.update(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )

    if not collect_referenced_names or not primary_target:
        return

    # The module reading of this import, from the one owner. ``import a.b as
    # c`` has always written this map; the ``from`` spelling of the same
    # binding wrote only the symbol reading, so ``c.name`` resolved to nothing
    # and the use was lost - in this lane and in the relationship lane alike.
    for alias_name, submodule in _from_import_module_bindings(
        node=node,
        resolved_target=primary_target,
        registry=registry,
    ):
        state.imported_module_aliases[alias_name] = submodule

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
    # A loaded Name is kept for the imported-symbol lane and no longer written
    # to ``referenced_names`` here: under liveness policy v5 the lexical pass
    # below decides which loads bind a definition of this module (evidence),
    # which are settled by a local, a parameter or a resolved import (neither
    # evidence nor signal), and which no scope settles - only those reach
    # ``referenced_names``. An attribute load stays a signal: its receiver
    # type is unknown, so the name really is loaded against every candidate
    # spelled that way.
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        state.name_nodes.append(node)
        return
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        state.referenced_names.add(node.attr)
        state.attr_nodes.append(node)


# --------------------------------------------------------------------------
# Lexical binding (liveness policy v5, criterion C).
#
# A loaded bare name used to be recorded as a reference to EVERY definition
# that shared its spelling, and that coincidence conferred LIVE. This pass
# resolves each Name load through Python's scoping rules instead - the local
# scope, the enclosing function scopes, the module, with a class scope
# visible only to loads written directly in its body - and answers three
# questions at once: which definitions of this module a load provably binds
# (evidence, module-level or function-local), which loads no scope settles
# (the bare-name signal, which now abstains instead of conferring LIVE), and
# which definitions sit under a function scope at all (the nested population
# that produced zero symbols under policy "4").
#
# Flow-insensitive on purpose, and biased in one direction only: a load that
# cannot be settled stays a signal, so imprecision here can move a symbol
# from LIVE to UNRESOLVED and never to DEAD. The one flow hazard that could
# settle a load wrongly - ``helper = helper`` in a class body reads the
# enclosing ``helper`` before rebinding it - is closed by construction: a
# class-body binding that is not a definition never settles a load, the
# search continues outward.

# Statement shapes that exist only on newer interpreters, resolved once: the
# supported matrix starts at 3.10, where ``TryStar`` (3.11) and ``TypeAlias``
# (3.12) are absent, and a reader must neither crash on them nor pretend
# they cannot occur.
_TRY_STATEMENTS: tuple[type[ast.stmt], ...] = tuple(
    statement
    for statement in (ast.Try, getattr(ast, "TryStar", None))
    if statement is not None
)
_TYPE_ALIAS_STATEMENT: type[ast.stmt] | None = getattr(ast, "TypeAlias", None)
_LexicalScopeKind = Literal["module", "class", "function", "lambda", "comprehension"]
_LexicalResolution = Literal["definition", "import", "local", "unbound", "ambiguous"]
_BINDING_DEFINITION: Final = "def:"
_BINDING_LOCAL: Final = "local"
_BINDING_IMPORT: Final = "import"
_BINDING_TYPE_PARAM: Final = "type_param"
_LOCALS_BOUNDARY: Final = ".<locals>."


class _NestedDeclaration(NamedTuple):
    """One definition under a function scope, as the walk discovers it.

    ``path`` is the module-local lexical path in CPython's ``__qualname__``
    spelling; ``parent_path`` is the path of the definition whose scope
    directly encloses this one (a function, or a class nested in one).
    """

    path: str
    parent_path: str
    node: _NamedDeclarationNode
    kind: NestedDefinitionKind


class _LexicalScope:
    """One scope of the lexical chain, mutated in place while it is built.

    A slots class rather than a dataclass, for the reason ``QualnameCollector``
    is one: a private working shape of the walk is not a model, and the
    phase-39S ratchet keeps dataclasses in the model store.
    """

    __slots__ = (
        "binding_count",
        "bindings",
        "global_names",
        "kind",
        "loads",
        "nonlocal_names",
        "parameters",
        "parent",
        "path",
        "simple_assignments",
        "star_import",
    )

    def __init__(
        self,
        kind: _LexicalScopeKind,
        parent: _LexicalScope | None,
        path: str,
    ) -> None:
        self.kind = kind
        self.parent = parent
        #: Lexical path of the definition that owns this scope; "" at module
        #: scope, and inherited by lambda and comprehension scopes.
        self.path = path
        self.bindings: dict[str, set[str]] = {}
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()
        self.loads: list[str] = []
        self.star_import = False
        #: How many times each name is bound here - a parameter, a store, a
        #: definition, an import alias each count once - so the escape proof
        #: can tell a name bound exactly once from one it cannot attribute to
        #: a single binding.
        self.binding_count: dict[str, int] = {}
        #: Parameter names of a function scope: values the caller supplied.
        self.parameters: set[str] = set()
        #: The value of every single-Name ``name = <expr>`` and
        #: ``name: T = <expr>`` statement, per name, for the escape proof's
        #: one-hop reading of a callee bound by assignment.
        self.simple_assignments: dict[str, list[ast.expr]] = {}


def _lexical_child_path(scope: _LexicalScope, name: str) -> str:
    if scope.kind == "module":
        return name
    if scope.kind == "class":
        return f"{scope.path}.{name}"
    return f"{scope.path}{_LOCALS_BOUNDARY}{name}"


def _lexical_module_scope(scope: _LexicalScope) -> _LexicalScope:
    while scope.parent is not None:
        scope = scope.parent
    return scope


def _lexical_binding_target(scope: _LexicalScope, name: str) -> _LexicalScope:
    """The scope a binding of ``name`` written in ``scope`` lands in.

    ``global x`` inside a function makes every binding of ``x`` there a
    module binding; the declaration is read before the body, so the routing
    is exact rather than order-dependent.
    """
    if scope.kind in {"function", "lambda"} and name in scope.global_names:
        return _lexical_module_scope(scope)
    return scope


def _lexical_bind(scope: _LexicalScope, name: str, kind: str) -> None:
    scope = _lexical_binding_target(scope, name)
    scope.bindings.setdefault(name, set()).add(kind)
    scope.binding_count[name] = scope.binding_count.get(name, 0) + 1


def _lexical_binding_scope(scope: _LexicalScope) -> _LexicalScope:
    """Where a walrus target binds: the nearest non-comprehension scope."""
    while scope.kind == "comprehension" and scope.parent is not None:
        scope = scope.parent
    return scope


def _lexical_arguments(args: ast.arguments) -> tuple[ast.arg, ...]:
    return tuple(
        arg
        for arg in (
            *args.posonlyargs,
            *args.args,
            args.vararg,
            *args.kwonlyargs,
            args.kwarg,
        )
        if arg is not None
    )


def _lexical_defaults(args: ast.arguments) -> tuple[ast.expr, ...]:
    return (
        *args.defaults,
        *(default for default in args.kw_defaults if default is not None),
    )


class _LexicalScopeBuilder:
    """One pass over a module: scopes, bindings, loads, nested definitions."""

    __slots__ = (
        "attribute_loads",
        "declarations",
        "decorator_roots",
        "definition_counts",
        "definition_nodes",
        "definitions",
        "enclosing_scopes",
        "own_scopes",
        "scopes",
    )

    def __init__(self) -> None:
        self.scopes: list[_LexicalScope] = []
        self.declarations: list[_NestedDeclaration] = []
        #: Every ``<Name>.<attr>`` load, with the scope the receiver name is
        #: written in: the receiver's binding is resolved there, never
        #: against a module-wide map.
        self.attribute_loads: list[tuple[_LexicalScope, str, str]] = []
        #: (definition path, decorator root name, the scope the decorator is
        #: EVALUATED in - the enclosing one, not the definition's own).
        self.decorator_roots: list[tuple[str, str, _LexicalScope]] = []
        #: Every definition the pass declared, in source order, with its
        #: module-local lexical path; the escape proof walks these.
        self.definitions: list[tuple[str, _NamedDeclarationNode]] = []
        #: Path -> node (the last declaration wins) and how many declarations
        #: spelled that path: a registrar spelled twice is no single callable.
        self.definition_nodes: dict[str, _NamedDeclarationNode] = {}
        self.definition_counts: dict[str, int] = {}
        #: Node id -> the scope its decorators are evaluated in, and the scope
        #: the definition itself owns.
        self.enclosing_scopes: dict[int, _LexicalScope] = {}
        self.own_scopes: dict[int, _LexicalScope] = {}

    def build(self, tree: ast.AST) -> _LexicalScope:
        module = _LexicalScope("module", None, "")
        self.scopes.append(module)
        statements = [
            child for child in ast.iter_child_nodes(tree) if isinstance(child, ast.stmt)
        ]
        self._visit_statements(statements, module)
        return module

    # -- statements ---------------------------------------------------------

    def _visit_statements(self, body: Sequence[ast.stmt], scope: _LexicalScope) -> None:
        # Declarations are read before the body they govern: ``global`` and
        # ``nonlocal`` are statements, and a binding above them in the source
        # is still a global binding at runtime.
        for statement in body:
            if isinstance(statement, ast.Global):
                scope.global_names.update(statement.names)
            elif isinstance(statement, ast.Nonlocal):
                scope.nonlocal_names.update(statement.names)
        for statement in body:
            self._visit_statement(statement, scope)

    def _visit_statement(self, node: ast.stmt, scope: _LexicalScope) -> None:
        self._record_simple_assignment(node, scope)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            self._visit_function(node, scope)
        elif isinstance(node, ast.ClassDef):
            self._visit_class(node, scope)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                _lexical_bind(scope, name, _BINDING_IMPORT)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    _lexical_module_scope(scope).star_import = True
                else:
                    _lexical_bind(scope, alias.asname or alias.name, _BINDING_IMPORT)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            return
        elif isinstance(node, _TRY_STATEMENTS):
            # ``ast.Try`` and, from 3.11, ``ast.TryStar``: the same four parts,
            # read by name so one branch covers both without a second shape.
            self._visit_statements(getattr(node, "body", []), scope)
            for handler in getattr(node, "handlers", []):
                if handler.type is not None:
                    self._visit_expression(handler.type, scope)
                if handler.name:
                    _lexical_bind(scope, handler.name, _BINDING_LOCAL)
                self._visit_statements(handler.body, scope)
            self._visit_statements(getattr(node, "orelse", []), scope)
            self._visit_statements(getattr(node, "finalbody", []), scope)
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                self._visit_expression(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._visit_expression(item.optional_vars, scope)
            self._visit_statements(node.body, scope)
        elif isinstance(node, ast.Match):
            self._visit_expression(node.subject, scope)
            for case in node.cases:
                self._visit_pattern(case.pattern, scope)
                if case.guard is not None:
                    self._visit_expression(case.guard, scope)
                self._visit_statements(case.body, scope)
        elif _TYPE_ALIAS_STATEMENT is not None and isinstance(
            node, _TYPE_ALIAS_STATEMENT
        ):
            # ``type X[T] = ...`` (3.12): the name binds like an assignment,
            # the parameters like type parameters, the value is an expression.
            # Read by name with a default because the statement type does
            # not exist on every supported interpreter.
            alias_name = getattr(node, "name", None)
            if isinstance(alias_name, ast.expr):
                self._visit_expression(alias_name, scope)
            for parameter in getattr(node, "type_params", []):
                _lexical_bind(scope, parameter.name, _BINDING_TYPE_PARAM)
            alias_value = getattr(node, "value", None)
            if isinstance(alias_value, ast.expr):
                self._visit_expression(alias_value, scope)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    self._visit_statement(child, scope)
                elif isinstance(child, ast.expr):
                    self._visit_expression(child, scope)

    def _visit_pattern(self, pattern: ast.pattern, scope: _LexicalScope) -> None:
        if isinstance(pattern, ast.MatchAs | ast.MatchStar) and pattern.name:
            _lexical_bind(scope, pattern.name, _BINDING_LOCAL)
        elif isinstance(pattern, ast.MatchMapping) and pattern.rest:
            _lexical_bind(scope, pattern.rest, _BINDING_LOCAL)
        for child in ast.iter_child_nodes(pattern):
            if isinstance(child, ast.pattern):
                self._visit_pattern(child, scope)
            elif isinstance(child, ast.expr):
                self._visit_expression(child, scope)

    def _declare(
        self,
        node: _NamedDeclarationNode,
        scope: _LexicalScope,
        kind: NestedDefinitionKind,
    ) -> str:
        path = _lexical_child_path(scope, node.name)
        _lexical_bind(scope, node.name, f"{_BINDING_DEFINITION}{path}")
        self.definitions.append((path, node))
        self.definition_nodes[path] = node
        self.definition_counts[path] = self.definition_counts.get(path, 0) + 1
        self.enclosing_scopes[id(node)] = scope
        if _LOCALS_BOUNDARY in path:
            self.declarations.append(_NestedDeclaration(path, scope.path, node, kind))
        return path

    def _record_attribute_receiver(
        self, node: ast.Attribute, scope: _LexicalScope
    ) -> None:
        """Keep a bare-Name receiver beside the scope it is written in."""
        if isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name):
            self.attribute_loads.append((scope, node.value.id, node.attr))

    def _record_decorator_roots(
        self,
        path: str,
        decorators: Sequence[ast.expr],
        scope: _LexicalScope,
    ) -> None:
        """Keep each decorator's root name beside the scope it resolves in.

        ``scope`` is the definition's ENCLOSING scope, which is where Python
        evaluates a decorator expression - so a parameter of the function
        that holds this definition is visible here, and that is exactly the
        binding the alias maps must not be read through.
        """
        for decorator in decorators:
            name = _decorator_expr_name(decorator)
            if name is None:
                continue
            self.decorator_roots.append((path, name.partition(".")[0], scope))

    def _record_simple_assignment(self, node: ast.stmt, scope: _LexicalScope) -> None:
        """Keep the value of a single-Name assignment beside its binding.

        Only the shapes the escape proof reads: ``name = <expr>`` with one
        Name target, and ``name: T = <expr>``. Unpacking, attribute and
        subscript targets, loop and ``with`` targets bind through
        ``_lexical_bind`` alone and stay unattributable on purpose.
        """
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                return
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.value is None:
                return
            name, value = node.target.id, node.value
        else:
            return
        owner = _lexical_binding_target(scope, name)
        owner.simple_assignments.setdefault(name, []).append(value)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: _LexicalScope
    ) -> None:
        path = self._declare(
            node, scope, "method" if scope.kind == "class" else "function"
        )
        # Decorators, defaults, annotations and the return annotation are
        # evaluated in the ENCLOSING scope: a parameter named like a decorator
        # must not capture the decorator's load.
        self._record_decorator_roots(path, node.decorator_list, scope)
        for decorator in node.decorator_list:
            self._visit_expression(decorator, scope)
        for default in _lexical_defaults(node.args):
            self._visit_expression(default, scope)
        for argument in _lexical_arguments(node.args):
            if argument.annotation is not None:
                self._visit_expression(argument.annotation, scope)
        if node.returns is not None:
            self._visit_expression(node.returns, scope)
        function = _LexicalScope("function", scope, path)
        self.scopes.append(function)
        self.own_scopes[id(node)] = function
        for parameter in getattr(node, "type_params", ()):
            _lexical_bind(function, parameter.name, _BINDING_TYPE_PARAM)
        for argument in _lexical_arguments(node.args):
            _lexical_bind(function, argument.arg, _BINDING_LOCAL)
            function.parameters.add(argument.arg)
        self._visit_statements(node.body, function)

    def _visit_class(self, node: ast.ClassDef, scope: _LexicalScope) -> None:
        path = self._declare(node, scope, "class")
        self._record_decorator_roots(path, node.decorator_list, scope)
        for decorator in node.decorator_list:
            self._visit_expression(decorator, scope)
        for base in node.bases:
            self._visit_expression(base, scope)
        for keyword in node.keywords:
            self._visit_expression(keyword.value, scope)
        klass = _LexicalScope("class", scope, path)
        self.scopes.append(klass)
        self.own_scopes[id(node)] = klass
        for parameter in getattr(node, "type_params", ()):
            _lexical_bind(klass, parameter.name, _BINDING_TYPE_PARAM)
        self._visit_statements(node.body, klass)

    # -- expressions --------------------------------------------------------

    def _visit_expression(self, node: ast.expr, scope: _LexicalScope) -> None:
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                scope.loads.append(node.id)
            else:
                _lexical_bind(scope, node.id, _BINDING_LOCAL)
        elif isinstance(node, ast.Attribute):
            # The attribute name is the receiver-blind signal
            # ``_collect_load_reference_node`` already records. The receiver
            # is kept WITH ITS SCOPE beside it, so the arms that used to read
            # a definition's owner off the receiver's spelling can ask what
            # the name actually binds here.
            self._record_attribute_receiver(node, scope)
            self._visit_expression(node.value, scope)
        elif isinstance(node, ast.NamedExpr):
            owner = _lexical_binding_scope(scope)
            if isinstance(node.target, ast.Name):
                _lexical_bind(owner, node.target.id, _BINDING_LOCAL)
            self._visit_expression(node.value, scope)
        elif isinstance(node, ast.Lambda):
            for default in _lexical_defaults(node.args):
                self._visit_expression(default, scope)
            inner = _LexicalScope("lambda", scope, scope.path)
            self.scopes.append(inner)
            for argument in _lexical_arguments(node.args):
                _lexical_bind(inner, argument.arg, _BINDING_LOCAL)
            self._visit_expression(node.body, inner)
        elif isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            inner = self._visit_generators(node.generators, scope)
            self._visit_expression(node.elt, inner)
        elif isinstance(node, ast.DictComp):
            inner = self._visit_generators(node.generators, scope)
            self._visit_expression(node.key, inner)
            self._visit_expression(node.value, inner)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    self._visit_expression(child, scope)
                elif isinstance(child, ast.keyword):
                    self._visit_expression(child.value, scope)

    def _visit_generators(
        self, generators: Sequence[ast.comprehension], scope: _LexicalScope
    ) -> _LexicalScope:
        # The outermost iterable is evaluated in the enclosing scope; every
        # target binds in the comprehension's own scope (Python 3 semantics).
        inner = _LexicalScope("comprehension", scope, scope.path)
        self.scopes.append(inner)
        for index, generator in enumerate(generators):
            self._visit_expression(generator.iter, scope if index == 0 else inner)
            self._visit_expression(generator.target, inner)
            for condition in generator.ifs:
                self._visit_expression(condition, inner)
        return inner


def _classify_lexical_binding(kinds: set[str]) -> tuple[_LexicalResolution, str | None]:
    definitions = {
        kind.removeprefix(_BINDING_DEFINITION)
        for kind in kinds
        if kind.startswith(_BINDING_DEFINITION)
    }
    others = {kind for kind in kinds if not kind.startswith(_BINDING_DEFINITION)}
    if len(definitions) == 1 and not others:
        return "definition", next(iter(definitions))
    if definitions:
        # A name the scope binds both as a definition and as something else
        # (``helper = decorate(helper)``) has no single binding a load can be
        # attributed to; it stays a signal.
        return "ambiguous", None
    if _BINDING_IMPORT in others:
        return "import", None
    return "local", None


def _lexical_binding_site(
    name: str, scope: _LexicalScope
) -> tuple[_LexicalScope, set[str]] | None:
    """The scope Python's lookup settles ``name`` in, and how it binds there.

    ``None`` when no scope of this module binds the name. Returning the SITE
    rather than only its classification is what lets a caller ask the second
    question the liveness lanes need: not just "what kind of binding is this"
    but "is that binding the module-level object my alias map describes, or
    something a body rebound".
    """

    current: _LexicalScope | None = scope
    innermost = True
    while current is not None:
        if current.kind == "class" and not innermost:
            current = current.parent
            continue
        if current.kind in {"function", "lambda"}:
            if name in current.global_names:
                module_scope = _lexical_module_scope(current)
                kinds = module_scope.bindings.get(name)
                return (module_scope, kinds) if kinds else None
            if name in current.nonlocal_names:
                current = current.parent
                innermost = False
                continue
        kinds = current.bindings.get(name)
        if kinds is not None and not (
            current.kind == "class"
            and not any(kind.startswith(_BINDING_DEFINITION) for kind in kinds)
        ):
            return current, kinds
        innermost = False
        current = current.parent
    return None


def _resolve_lexical_load(
    name: str, scope: _LexicalScope
) -> tuple[_LexicalResolution, str | None]:
    """Python's lookup for one loaded name, over the scope chain."""

    site = _lexical_binding_site(name, scope)
    if site is None:
        return "unbound", None
    return _classify_lexical_binding(site[1])


class _ProvenBinding(NamedTuple):
    """What a receiver name is PROVEN to bind at the site it is written.

    Liveness policy v5, same generation, correcting the arms that read the
    owner off a spelling: a qualified spelling carries no liveness authority
    until the receiver binding is proven, so this is the only door through
    which ``receiver.attr`` may name a definition.

    ``kind`` is ``"definition"`` with the module-local lexical ``path`` of the
    definition the receiver binds, or ``"import"`` when the receiver binds an
    import and nothing else. Every other outcome - a parameter, a local, a
    loop or comprehension target, a name bound both as a definition and as
    something else, a name bound by an import AND rebound - is not proven and
    has no entry here: the caller must abstain.
    """

    kind: Literal["definition", "import"]
    path: str | None


def _proven_receiver_binding(name: str, scope: _LexicalScope) -> _ProvenBinding | None:
    """The proven binding of a receiver name loaded in ``scope``, or ``None``.

    ``_classify_lexical_binding`` answers a different question - whether a
    load is SETTLED, so that an unsettled one stays a bare-name signal - and
    it deliberately calls a name bound as both an import and a local
    "import", because either way the load is not this module's to explain.
    Authority is the stricter question, so the import arm is re-checked here
    against the raw kinds instead of being taken from that verdict.
    """

    site = _lexical_binding_site(name, scope)
    if site is None:
        return None
    _binding_scope, kinds = site
    resolution, path = _classify_lexical_binding(kinds)
    if resolution == "definition" and path is not None:
        return _ProvenBinding("definition", path)
    if resolution == "import" and kinds == {_BINDING_IMPORT}:
        return _ProvenBinding("import", None)
    return None


def _decorator_root_binds_module_object(name: str, scope: _LexicalScope) -> bool:
    """Whether a decorator's root name binds the module-level object the
    walk's alias maps describe, rather than a value some body supplied.

    The external-alias and hook-marker maps are module-wide by construction:
    they record what an import statement resolved to, and what a module-level
    assignment proved to be a pluggy marker. Both are statements ABOUT the
    module scope, so a decorator whose root the enclosing function bound -
    a parameter, a loop target, a comprehension variable, a local - is not
    the object either map describes, and the spelling it shares with one
    proves nothing.

    A function-local ``import`` is admitted: the name then binds a module
    object at that very site, which is the same fact the map records, only
    written closer in.
    """

    site = _lexical_binding_site(name, scope)
    if site is None:
        return False
    binding_scope, kinds = site
    if kinds == {_BINDING_IMPORT}:
        return True
    resolution, _path = _classify_lexical_binding(kinds)
    return binding_scope.kind == "module" and resolution != "ambiguous"


class _LexicalBindingFacts(NamedTuple):
    #: Definitions of this module a load provably binds, as module-local
    #: lexical paths; self-references excluded.
    bound_definition_paths: frozenset[str]
    #: Loaded names no scope of this module settles.
    unsettled_names: frozenset[str]
    #: Bare names PROVEN to bind an import at some load site, so the
    #: imported-symbol arm may name what the import binds.
    import_bound_names: frozenset[str]
    #: ``(receiver, attribute)`` pairs whose receiver is proven to bind an
    #: import at that site - the only pairs the imported-module-attribute arm
    #: may resolve through the module-wide alias map.
    import_bound_attributes: frozenset[tuple[str, str]]
    #: ``(definition path, attribute)`` pairs whose receiver is proven to
    #: bind that definition at that site - the only pairs the same-module
    #: class-attribute arm may resolve.
    definition_bound_attributes: frozenset[tuple[str, str]]
    #: ``(definition path, decorator root name)`` pairs whose root provably
    #: binds the module-level object the walk's alias maps describe.
    proven_decorator_roots: frozenset[tuple[str, str]]
    #: Every definition under a function scope, in source order.
    nested_declarations: tuple[_NestedDeclaration, ...]
    #: Module-local lexical path -> the proven opaque-escape flow of the
    #: definition's value (liveness policy v5); absent when none was proven.
    escape_witnesses: Mapping[str, str]


def _collect_lexical_binding_facts(
    tree: ast.AST,
    *,
    settled_import_names: frozenset[str],
    external_import_names: frozenset[str] = frozenset(),
) -> _LexicalBindingFacts:
    """Run the lexical pass; ``settled_import_names`` are the aliases a
    resolved import binds, whose loads the imported-symbol lane already
    answers for. A load bound by any other import - external, or one the
    registry could not place, which is the shape of a script-style sibling
    module - stays a signal: the resolver knows the load is not this
    module's, not where it goes."""

    builder = _LexicalScopeBuilder()
    builder.build(tree)
    bound, unsettled, import_bound_names = _lexical_load_facts(
        builder,
        settled_import_names=settled_import_names,
    )
    import_bound_attributes, definition_bound_attributes = _attribute_receiver_facts(
        builder
    )
    return _LexicalBindingFacts(
        bound_definition_paths=bound,
        unsettled_names=unsettled,
        import_bound_names=import_bound_names,
        import_bound_attributes=import_bound_attributes,
        definition_bound_attributes=definition_bound_attributes,
        proven_decorator_roots=frozenset(
            (path, root)
            for path, root, scope in builder.decorator_roots
            if _decorator_root_binds_module_object(root, scope)
        ),
        nested_declarations=tuple(builder.declarations),
        escape_witnesses=_collect_opaque_escape_witnesses(
            builder,
            internal_import_names=settled_import_names,
            external_import_names=external_import_names,
        ),
    )


def _lexical_load_facts(
    builder: _LexicalScopeBuilder,
    *,
    settled_import_names: frozenset[str],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """What every bare-name load of this module settles to.

    Returns the definitions a load provably binds, the loads no scope
    settles, and the names PROVEN to bind an import - evidence, signal, and
    the imported-symbol lane's authority, in that order.
    """

    bound: set[str] = set()
    unsettled: set[str] = set()
    import_bound: set[str] = set()
    for scope in builder.scopes:
        for name in scope.loads:
            resolution, path = _resolve_lexical_load(name, scope)
            proven = _proven_receiver_binding(name, scope)
            if proven is not None and proven.kind == "import":
                import_bound.add(name)
            if resolution == "definition":
                # A definition loading its own name is not its own consumer:
                # neither evidence nor a signal.
                if path != scope.path:
                    bound.add(path or "")
                continue
            if resolution == "local":
                continue
            # Everything left is a signal, except a load the imported-symbol
            # lane still ANSWERS for. Once that lane requires a proven
            # binding, a load it refuses is no longer answered for and must
            # not be silenced: a name bound both by an import and by a
            # module-level rebinding (``from x import y`` then
            # ``y = wrap(y)``) has no single owner, and dropping both its
            # evidence and its signal reported the imported definition DEAD
            # while the module called the wrapper around it. Measured: that
            # verdict flipped LIVE -> DEAD on a three-line fixture before
            # ``proven is None`` joined this condition.
            if (
                resolution != "import"
                or name not in settled_import_names
                or proven is None
            ):
                unsettled.add(name)
    return frozenset(bound), frozenset(unsettled), frozenset(import_bound)


def _attribute_receiver_facts(
    builder: _LexicalScopeBuilder,
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """The ``receiver.attribute`` pairs whose receiver binding is PROVEN.

    Keyed by the pair rather than by the receiver alone: one spelling can be
    an import in one scope and a parameter in the next, and only the site
    that proved it may name a definition.
    """

    imported: set[tuple[str, str]] = set()
    defined: set[tuple[str, str]] = set()
    for scope, receiver, attribute in builder.attribute_loads:
        proven = _proven_receiver_binding(receiver, scope)
        if proven is None:
            continue
        if proven.kind == "import":
            imported.add((receiver, attribute))
        elif proven.path is not None:
            defined.add((proven.path, attribute))
    return frozenset(imported), frozenset(defined)


# --------------------------------------------------------------------------
# Opaque internal escape (liveness policy v5, the same generation).
#
# Measured on this repository at 5f35a50f: eight MCP resource handlers carry
# a bare ``@resource(...)`` whose name binds to a function-local
# ``def resource`` that hands the decorated function to ``mcp.resource(...)``
# - a callable this analyzer resolves to no definition - and the lane called
# them DEAD. The rule below does not prove such a symbol live; it proves
# DEAD may no longer be asserted:
#
#     decorated definition
#     + the innermost decorator lexically resolves to a local callable
#     + the decorated value provably flows into an opaque callable
#     + the analyzer cannot establish what that consumer does
#     ----------------------------------------------------------------
#     DEAD is forbidden -> UNRESOLVED (opaque_internal_escape), both worlds
#
# Narrow and constructive by design, not a general escape engine. The proof
# follows exactly one registrar, at most one returned inner function, and a
# DIRECT argument position; every statement it walks past is straight-line;
# the callee root is read through at most three assignment aliases. Where
# the proof cannot be completed - a registration behind a conditional, two
# returns, a re-assigned parameter, a value routed through a call the
# analyzer CAN resolve - nothing is emitted and the symbol stays dead: the
# failure to avoid is "when in doubt, abstain", which erodes the dead lane.
# Every witness names the proven flow; no name coincidence can produce one.

_ESCAPE_STRAIGHT_LINE_STATEMENTS: tuple[type[ast.stmt], ...] = (
    ast.Expr,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Pass,
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assert,
    # Declarations, not control flow; a declaration of the PARAMETER itself
    # is refused separately by ``_escape_parameter_is_stable``.
    ast.Global,
    ast.Nonlocal,
)
#: How many ``name = <alias>`` hops the callee classification follows before
#: it gives up (``unknown``, which never fires).
_ESCAPE_ALIAS_HOPS: Final = 3
_EscapeCallee = Literal["resolvable", "opaque", "unknown"]


def _collect_opaque_escape_witnesses(
    builder: _LexicalScopeBuilder,
    *,
    internal_import_names: frozenset[str],
    external_import_names: frozenset[str],
) -> dict[str, str]:
    """Module-local lexical path -> witness, for every definition whose
    innermost decorator binds to a local registrar with a proven flow of the
    decorated value into an opaque callable. Keyed on the BINDING the
    decorator's name resolves to, never on the name."""

    witnesses: dict[str, str] = {}
    for path, node in builder.definitions:
        witness = _escape_witness_for_definition(
            node,
            builder,
            internal_import_names=internal_import_names,
            external_import_names=external_import_names,
        )
        if witness is not None:
            witnesses[path] = witness
    return witnesses


def _escape_witness_for_definition(
    node: _NamedDeclarationNode,
    builder: _LexicalScopeBuilder,
    *,
    internal_import_names: frozenset[str],
    external_import_names: frozenset[str],
) -> str | None:
    if not node.decorator_list:
        return None
    # Only the innermost decorator receives the definition itself; an outer
    # one receives whatever the inner returned, which is not this value.
    decorator = node.decorator_list[-1]
    root = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not isinstance(root, ast.Name):
        return None
    resolution, registrar_path = _resolve_lexical_load(
        root.id, builder.enclosing_scopes[id(node)]
    )
    if resolution != "definition" or registrar_path is None:
        return None
    if builder.definition_counts.get(registrar_path) != 1:
        return None
    registrar = builder.definition_nodes[registrar_path]
    if not isinstance(registrar, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    entry = _escape_entry_function(decorator, registrar, builder)
    if entry is None:
        return None
    positional = [*entry.args.posonlyargs, *entry.args.args]
    if not positional:
        return None
    parameter = positional[0].arg
    if not _escape_parameter_is_stable(entry, parameter):
        return None
    entry_scope = builder.own_scopes[id(entry)]
    for call in _escape_consuming_calls(entry, parameter):
        leaf, dotted = _escape_callee_root(call.func)
        if not isinstance(leaf, ast.Name) or dotted is None:
            continue
        verdict, origin = _escape_classify_callee(
            leaf.id,
            dotted,
            entry_scope,
            builder,
            internal_import_names=internal_import_names,
            external_import_names=external_import_names,
            hops=_ESCAPE_ALIAS_HOPS,
        )
        if verdict == "opaque":
            spelled = f"{root.id}(...)" if isinstance(decorator, ast.Call) else root.id
            return escape_witness(spelled, registrar_path, parameter, origin)
    return None


def _escape_entry_function(
    decorator: ast.expr,
    registrar: _qualnames.FunctionNode,
    builder: _LexicalScopeBuilder,
) -> _qualnames.FunctionNode | None:
    """The function that receives the decorated value as its first parameter.

    ``@registrar`` hands it to the registrar itself. ``@registrar(...)`` hands
    it to whatever the registrar RETURNS, which the proof admits only when
    the registrar's body is straight-line with exactly one ``return`` of a
    name bound once, as a function defined directly in that body. Two
    returns, a conditional, a returned call: no entry function, no proof.
    """
    if not isinstance(decorator, ast.Call):
        return registrar
    returns = [
        statement for statement in registrar.body if isinstance(statement, ast.Return)
    ]
    if len(returns) != 1 or not all(
        isinstance(statement, _ESCAPE_STRAIGHT_LINE_STATEMENTS)
        for statement in registrar.body
        if not isinstance(statement, ast.Return)
    ):
        return None
    returned = returns[0].value
    if not isinstance(returned, ast.Name):
        return None
    scope = builder.own_scopes[id(registrar)]
    inner_path = f"{scope.path}{_LOCALS_BOUNDARY}{returned.id}"
    if (
        scope.bindings.get(returned.id) != {f"{_BINDING_DEFINITION}{inner_path}"}
        or scope.binding_count.get(returned.id) != 1
        or builder.definition_counts.get(inner_path) != 1
    ):
        return None
    inner = builder.definition_nodes[inner_path]
    if not isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef) or not any(
        statement is inner for statement in registrar.body
    ):
        return None
    return inner


def _escape_parameter_is_stable(node: _qualnames.FunctionNode, parameter: str) -> bool:
    """The parameter is never stored, deleted or re-declared anywhere inside."""
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and child.id == parameter
            and not isinstance(child.ctx, ast.Load)
        ):
            return False
        if isinstance(child, ast.Global | ast.Nonlocal) and parameter in child.names:
            return False
    return True


def _escape_consuming_calls(
    node: _qualnames.FunctionNode, parameter: str
) -> Iterator[ast.Call]:
    """Calls that receive the parameter as a DIRECT argument, reached
    unconditionally: top-level ``Expr``, ``Assign``, ``AnnAssign`` and
    ``Return`` statements, scanned in order until the first ``return`` or the
    first statement that is not straight-line."""
    for statement in node.body:
        value: ast.expr | None = None
        if isinstance(statement, ast.Expr | ast.Return | ast.Assign | ast.AnnAssign):
            value = statement.value
        if isinstance(value, ast.Call) and _escape_call_receives(value, parameter):
            yield value
        if isinstance(statement, ast.Return) or not isinstance(
            statement, _ESCAPE_STRAIGHT_LINE_STATEMENTS
        ):
            return


def _escape_call_receives(call: ast.Call, parameter: str) -> bool:
    return any(
        isinstance(argument, ast.Name) and argument.id == parameter
        for argument in call.args
    ) or any(
        isinstance(keyword.value, ast.Name) and keyword.value.id == parameter
        for keyword in call.keywords
    )


def _escape_callee_root(expr: ast.expr) -> tuple[ast.expr, str | None]:
    """The leaf of a callee chain and its dotted spelling.

    ``mcp.resource(uri)`` -> (``mcp``, ``"mcp.resource"``); calls and
    subscripts along the chain are peeled, attributes are kept in order.
    A chain that does not bottom out in a Name spells nothing.
    """
    attributes: list[str] = []
    current = expr
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            attributes.append(current.attr)
            current = current.value
        elif isinstance(current, ast.Subscript):
            current = current.value
        else:
            break
    if not isinstance(current, ast.Name):
        return current, None
    return current, ".".join([current.id, *reversed(attributes)])


def _escape_binding_scope(name: str, scope: _LexicalScope) -> _LexicalScope | None:
    """The scope ``_resolve_lexical_load`` would read ``name`` from, or ``None``
    when no scope of the chain binds it (a builtin, a star-imported name, a
    ``global`` declaration the module never binds)."""
    current: _LexicalScope | None = scope
    innermost = True
    while current is not None:
        if current.kind == "class" and not innermost:
            current = current.parent
            continue
        if current.kind in {"function", "lambda"}:
            if name in current.global_names:
                module = _lexical_module_scope(current)
                return module if name in module.bindings else None
            if name in current.nonlocal_names:
                current = current.parent
                innermost = False
                continue
        kinds = current.bindings.get(name)
        if kinds is not None and not (
            current.kind == "class"
            and not any(kind.startswith(_BINDING_DEFINITION) for kind in kinds)
        ):
            return current
        innermost = False
        current = current.parent
    return None


def _escape_nonlocal_rebinds(
    scope: _LexicalScope, name: str, builder: _LexicalScopeBuilder
) -> bool:
    """Whether a scope nested in ``scope`` declares ``name`` nonlocal."""
    for candidate in builder.scopes:
        if name not in candidate.nonlocal_names:
            continue
        parent = candidate.parent
        while parent is not None:
            if parent is scope:
                return True
            parent = parent.parent
    return False


def _escape_classify_callee(
    name: str,
    dotted: str,
    scope: _LexicalScope,
    builder: _LexicalScopeBuilder,
    *,
    internal_import_names: frozenset[str],
    external_import_names: frozenset[str],
    hops: int,
) -> tuple[_EscapeCallee, str]:
    """What the analyzer can say about the callee rooted at ``name``.

    ``resolvable``: the root binds to a definition of this module or to an
    import placed inside the analysis root, directly or through assignment
    aliases - a consumer the analyzer can see, so the rule does not fire.
    ``opaque``: an external import, a parameter (a value the caller
    supplied), or a name bound once to the RESULT of a call - a callable this
    analyzer resolves to no definition. ``unknown``: everything the proof
    cannot attribute (an unbound or star-imported name, an import the
    registry could not place, a name bound more than once or by unpacking,
    a literal), which never fires. The second element is the dotted origin
    the witness spells: the assigned call for a call result, the callee
    itself otherwise.
    """
    # One walk, not two: the scope that binds the name is found once, and
    # its kinds are classified exactly as ``_resolve_lexical_load`` would
    # classify them; a name no scope binds (a builtin, a star import) has no
    # scope to read and never fires.
    binding_scope = _escape_binding_scope(name, scope)
    if binding_scope is None:
        return "unknown", dotted
    resolution, _path = _classify_lexical_binding(binding_scope.bindings[name])
    if resolution == "definition":
        return "resolvable", dotted
    if resolution == "import":
        if name in external_import_names:
            return "opaque", dotted
        if name in internal_import_names:
            return "resolvable", dotted
        return "unknown", dotted
    if resolution != "local":
        return "unknown", dotted
    if name in binding_scope.parameters:
        return "opaque", dotted
    values = binding_scope.simple_assignments.get(name, [])
    if (
        len(values) != 1
        or binding_scope.binding_count.get(name) != 1
        or _escape_nonlocal_rebinds(binding_scope, name, builder)
    ):
        return "unknown", dotted
    value = values[0]
    leaf, origin = _escape_callee_root(value)
    if not isinstance(leaf, ast.Name) or origin is None:
        return "unknown", dotted
    if isinstance(value, ast.Call):
        return "opaque", origin
    if isinstance(value, ast.Name | ast.Attribute) and hops > 0:
        return _escape_classify_callee(
            leaf.id,
            origin,
            binding_scope,
            builder,
            internal_import_names=internal_import_names,
            external_import_names=external_import_names,
            hops=hops - 1,
        )
    return "unknown", dotted


@dataclass(frozen=True, slots=True)
class _RelationshipImportIndex:
    symbol_bindings: dict[str, frozenset[str]]
    module_bindings: dict[str, frozenset[str]]
    module_shadowed_names: frozenset[str]


_EMPTY_RELATIONSHIP_IMPORTS = _RelationshipImportIndex({}, {}, frozenset())


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
        return _EMPTY_RELATIONSHIP_IMPORTS

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
                for alias_name, submodule in _from_import_module_bindings(
                    node=node,
                    resolved_target=target,
                    registry=registry,
                ):
                    module_bindings.setdefault(alias_name, set()).add(submodule)
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


def _local_import_shadow(scope_node: ast.AST) -> str | None:
    """A name this scope node binds by something OTHER than an import.

    A body that imports a name and then assigns it again does not reach the
    imported symbol at the call, so the local import reading is withdrawn for
    exactly those names - the same conservative rule the module-scope index
    applies through ``module_shadowed_names``.
    """
    if isinstance(scope_node, ast.Name) and isinstance(
        scope_node.ctx, ast.Store | ast.Del
    ):
        return scope_node.id
    return _scope_declaration_binding_name(scope_node)


def _local_relationship_imports(
    scope_nodes: tuple[ast.AST, ...],
    *,
    parameter_names: frozenset[str],
    source: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
) -> _RelationshipImportIndex:
    """The imports a function body performs, resolved by the module-scope rule.

    ``_collect_relationship_import_index`` stops at every function, so before
    this an import written INSIDE a body reached the resolver as an opaque
    caller binding and every use of it resolved to nothing - while the module
    walk, which does descend, recorded the very same binding. That is why the
    witness lane alone lost the reference. Resolution here is the module-scope
    rule verbatim, module reading included, so the dialect is answered the
    same way at whatever scope it is written and for whichever lane the file
    belongs to.
    """
    symbol_bindings: dict[str, set[str]] = {}
    module_bindings: dict[str, set[str]] = {}
    shadowed_names: set[str] = set(parameter_names)
    for scope_node in scope_nodes:
        if isinstance(scope_node, ast.Import):
            for alias in scope_node.names:
                alias_name = alias.asname or alias.name.split(".", 1)[0]
                module_bindings.setdefault(alias_name, set()).add(alias.name)
            continue
        if isinstance(scope_node, ast.ImportFrom):
            target = resolve_import_observation(
                source, scope_node, registry
            ).resolved_target
            if target:
                for alias in scope_node.names:
                    if alias.name != "*":
                        alias_name = alias.asname or alias.name
                        symbol_bindings.setdefault(alias_name, set()).add(
                            f"{target}:{alias.name}"
                        )
                for alias_name, submodule in _from_import_module_bindings(
                    node=scope_node,
                    resolved_target=target,
                    registry=registry,
                ):
                    module_bindings.setdefault(alias_name, set()).add(submodule)
            continue
        if isinstance(scope_node, ast.Global | ast.Nonlocal):
            shadowed_names.update(scope_node.names)
            continue
        shadow = _local_import_shadow(scope_node)
        if shadow is not None:
            shadowed_names.add(shadow)
    return _RelationshipImportIndex(
        symbol_bindings=_freeze_relationship_bindings(symbol_bindings),
        module_bindings=_freeze_relationship_bindings(module_bindings),
        module_shadowed_names=frozenset(sorted(shadowed_names)),
    )


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
        return None, RESOLUTION_UNRESOLVED_NAME
    if len(targets) != 1:
        return None, RESOLUTION_AMBIGUOUS_IMPORT
    return next(iter(targets)), resolved_rule


def _module_attribute_target(
    targets: frozenset[str],
    *,
    attr: str,
) -> tuple[str | None, str]:
    """``<module binding>.<attr>`` as one qualname, or why it is not one."""
    target_module, rule = _single_relationship_target(
        targets,
        resolved_rule=RESOLUTION_IMPORTED_MODULE_ATTRIBUTE,
    )
    if target_module is None:
        return None, rule
    return f"{target_module}:{attr}", rule


def _local_import_targets(
    name: str,
    *,
    bindings: dict[str, frozenset[str]],
    local_imports: _RelationshipImportIndex,
) -> frozenset[str] | None:
    """What the function's OWN import bound this name to, if it still holds.

    ``None`` means the body imported no such name, or imported it and then
    rebound it - in which case the call does not reach the imported symbol and
    naming it would invent a consumer.
    """
    targets = bindings.get(name)
    if not targets or name in local_imports.module_shadowed_names:
        return None
    return targets


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
    # The imports the CALLING body performs. Defaulted to the empty index -
    # the honest neutral element for a scope that imports nothing - so this
    # resolver stays callable with the module-scope facts alone.
    local_imports: _RelationshipImportIndex = _EMPTY_RELATIONSHIP_IMPORTS,
) -> tuple[str | None, str]:
    if isinstance(node, ast.Name):
        # The nearest binding wins, and a function-local import is nearer than
        # anything at module scope. It is also the ONLY reading under which
        # the name is not an opaque caller binding, which is what the guard
        # below would otherwise make of it.
        local_targets = _local_import_targets(
            node.id,
            bindings=local_imports.symbol_bindings,
            local_imports=local_imports,
        )
        if local_targets is not None:
            return _single_relationship_target(
                local_targets,
                resolved_rule="imported_symbol",
            )
        import_targets = imports.symbol_bindings.get(node.id)
        if import_targets and (
            node.id in caller_bindings or node.id in imports.module_shadowed_names
        ):
            return None, RESOLUTION_LOCAL_SHADOWING
        if import_targets:
            return _single_relationship_target(
                import_targets,
                resolved_rule=RESOLUTION_IMPORTED_SYMBOL,
            )
        if node.id in caller_bindings:
            return None, RESOLUTION_UNRESOLVED_NAME
        if node.id in top_level_function_names:
            return f"{module_name}:{node.id}", RESOLUTION_SAME_MODULE_FUNCTION
        if node.id in top_level_class_names:
            return f"{module_name}:{node.id}", RESOLUTION_SAME_MODULE_CLASS
        return None, RESOLUTION_UNRESOLVED_NAME

    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base_name = node.value.id
        local_targets = _local_import_targets(
            base_name,
            bindings=local_imports.module_bindings,
            local_imports=local_imports,
        )
        if local_targets is not None:
            return _module_attribute_target(local_targets, attr=node.attr)
        import_targets = imports.module_bindings.get(base_name)
        if import_targets and (
            base_name in caller_bindings or base_name in imports.module_shadowed_names
        ):
            return None, RESOLUTION_LOCAL_SHADOWING
        if import_targets:
            return _module_attribute_target(import_targets, attr=node.attr)
        # The receiver parameter (self/cls) is itself a caller binding, so the
        # self/cls case must precede the generic caller-shadow guard below.
        if (
            receiver_name is not None
            and enclosing_class_local is not None
            and base_name == receiver_name
        ):
            candidate = f"{module_name}:{enclosing_class_local}.{node.attr}"
            if candidate in local_method_qualnames:
                return candidate, RESOLUTION_SELF_OR_CLS_METHOD
            return None, RESOLUTION_UNRESOLVED_DYNAMIC
        if base_name in top_level_class_names and base_name not in caller_bindings:
            candidate = f"{module_name}:{base_name}.{node.attr}"
            if candidate in local_method_qualnames:
                return candidate, RESOLUTION_SAME_MODULE_CLASS_METHOD
            return None, RESOLUTION_UNRESOLVED_DYNAMIC
    return None, RESOLUTION_UNRESOLVED_DYNAMIC


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
        resolution_rule=validate_resolution_rule(resolution_rule),
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
        local_imports = _local_relationship_imports(
            scope_nodes,
            parameter_names=frozenset(_function_parameter_names(function_node)),
            source=source,
            registry=registry,
        )
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
                local_imports=local_imports,
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
                local_imports=local_imports,
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
    lexical_binding_paths: frozenset[str],
    import_bound_names: frozenset[str],
    import_bound_attributes: frozenset[tuple[str, str]],
    definition_bound_attributes: frozenset[tuple[str, str]],
    proven_decorator_roots: frozenset[tuple[str, str]],
) -> frozenset[str]:
    """Which definitions this module's loads PROVABLY reference.

    Liveness policy v5, same generation. Every arm below used to recover the
    owner of a reference from a SPELLING: the loaded name was looked up in a
    module-wide map (what an import bound, which classes this module declares)
    with no regard for what the name binds where it is written. Measured on a
    two-class fixture, a parameter that merely spelled a class name held that
    class's method live, and the negative arm - an identically shaped class
    nothing mentions - stayed dead, so the receiver's spelling was the whole
    cause.

    The three ``*_bound_*`` facts are that missing proof, resolved by the
    lexical pass in the scope each load is written in. A receiver whose
    binding is not proven contributes nothing here; its ATTRIBUTE name is
    already a bare-name signal (``_collect_load_reference_node``), so the
    symbol abstains as ``ambiguous_internal_binding`` instead of being called
    live. That backstop is what makes tightening safe in this lane: refusing
    unproven evidence here moves a symbol from LIVE to UNRESOLVED, never to
    DEAD.
    """
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
        if name_node.id in import_bound_names:
            resolved.update(state.imported_symbol_bindings.get(name_node.id, ()))

    for attr_node in state.attr_nodes:
        qualname = _proven_attribute_reference(
            attr_node,
            module_name=module_name,
            state=state,
            top_level_class_by_name=top_level_class_by_name,
            local_method_qualnames=local_method_qualnames,
            import_bound_attributes=import_bound_attributes,
            definition_bound_attributes=definition_bound_attributes,
        )
        if qualname is not None:
            resolved.add(qualname)

    # No ``__all__`` arm here, by liveness policy v4 (RULING 2026-09-01,
    # corrected 2026-09-03): a static ``__all__`` member used to be folded in
    # at this point, where it was indistinguishable from a call site, and it
    # held 104 symbols of this repository live that nothing inside the product
    # binds. Listing a name declares what ``import *`` carries and what the
    # module exports; it references nothing. The declaration keeps its two
    # honest jobs elsewhere: ``star_import_bound_qualnames`` below, and the
    # ``declared_exports`` fact the external-reachability owner reads.

    # Liveness policy v2: the PEP 484 explicit re-export proof, independent
    # of ``__all__``. Targets were resolved to exact identity at collection
    # time, so this is a plain union.
    resolved.update(state.explicit_reexport_qualnames)

    # Liveness policy v5: a loaded Name resolved through the lexical scope
    # chain to a definition of this module - a top-level function or class,
    # a method loaded in its class body, or a function-local definition.
    # Symbol-specific by Python's own rules, which is what the bare-name
    # coincidence never was.
    resolved.update(f"{module_name}:{path}" for path in lexical_binding_paths)

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
        proven_decorator_roots=proven_decorator_roots,
    )
    resolved.update(external_decorator_roots)
    state.liveness_root_reasons.update(external_decorator_roots)

    return frozenset(resolved)


def _proven_attribute_reference(
    attr_node: ast.Attribute,
    *,
    module_name: str,
    state: _ModuleWalkState,
    top_level_class_by_name: Mapping[str, str],
    local_method_qualnames: frozenset[str],
    import_bound_attributes: frozenset[tuple[str, str]],
    definition_bound_attributes: frozenset[tuple[str, str]],
) -> str | None:
    """The definition one ``receiver.attr`` load PROVABLY names, if any.

    Both arms keep the target map they always read - the module-wide import
    aliases, the top-level classes of this module - and gain the binding
    proof in front of it, so the change is subtractive only. A receiver
    proven to bind a NESTED class would resolve here too and is deliberately
    left out: admitting it would ADD liveness, which is a widening and a
    separate decision, not this correction.
    """

    base = attr_node.value
    if not isinstance(base, ast.Name):
        return None
    pair = (base.id, attr_node.attr)
    if pair in import_bound_attributes:
        imported_module = state.imported_module_aliases.get(base.id)
        if imported_module is not None:
            return f"{imported_module}:{attr_node.attr}"
    if pair not in definition_bound_attributes:
        return None
    class_qualname = top_level_class_by_name.get(base.id)
    if class_qualname is None:
        return None
    local_method_qualname = f"{module_name}:{class_qualname}.{attr_node.attr}"
    if local_method_qualname not in local_method_qualnames:
        return None
    return local_method_qualname


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
    proven_decorator_roots: frozenset[tuple[str, str]],
) -> dict[str, _LocalLivenessRootReason]:
    hook_marker_aliases = _resolve_hook_marker_aliases(state)
    overload_aliases = frozenset(state.non_runtime_decorator_aliases)
    # The producer's door, not the decoder's: a reason this build has retired
    # is still decodable from a stored row and must never be minted here.
    emit_live_root_reason(LIVENESS_EXTERNAL_DECORATOR)
    return {
        f"{module_name}:{local_name}": LIVENESS_EXTERNAL_DECORATOR
        for local_name, function_node in collector.units
        if _external_decorator_roots_function(
            function_node,
            external_symbol_aliases=frozenset(state.external_symbol_aliases),
            external_module_aliases=frozenset(state.external_module_aliases),
            local_top_level_names=local_top_level_names,
            hook_marker_aliases=hook_marker_aliases,
            overload_aliases=overload_aliases,
            proven_roots=proven_roots_for(proven_decorator_roots, local_name),
        )
    }


def proven_roots_for(
    proven_decorator_roots: frozenset[tuple[str, str]],
    path: str,
) -> frozenset[str]:
    """The decorator root names proven to bind a module object for ``path``.

    The walk keys the proof by the definition's module-local lexical path,
    which for a module-level function or a class-body method is the same
    string the qualname collector uses, and for a function-local definition
    is the ``<locals>`` path the nested population is keyed by. One join, two
    call sites.
    """
    return frozenset(root for owner, root in proven_decorator_roots if owner == path)


def _external_decorator_roots_function(
    function_node: _qualnames.FunctionNode,
    *,
    external_symbol_aliases: frozenset[str],
    external_module_aliases: frozenset[str],
    local_top_level_names: frozenset[str],
    hook_marker_aliases: frozenset[str],
    overload_aliases: frozenset[str],
    proven_roots: frozenset[str] = frozenset(),
) -> bool:
    """The external-decorator root rule for one function, any lexical depth.

    An ``@overload`` stub is a DECLARATION of this symbol, not a use of it:
    every stub shares the implementation's qualname, so admitting one lets a
    symbol stand as its own external evidence. ``typing.overload`` resolves
    through an external module alias and is otherwise indistinguishable from
    a framework registration, which is how a method whose only real evidence
    was an ordinary call site came to be recorded as live because something
    external decorated it.
    """
    if _is_typing_overload_stub(function_node, overload_aliases=overload_aliases):
        return False
    return _has_external_decorator(
        function_node,
        external_symbol_aliases=external_symbol_aliases,
        external_module_aliases=external_module_aliases,
        local_top_level_names=local_top_level_names,
        proven_roots=proven_roots,
    ) or _has_hook_marker_decorator(
        function_node,
        hook_marker_aliases,
        proven_roots=proven_roots,
    )


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
        base_names, has_unresolved_external_base = _class_base_facts_for_node(
            class_node,
            external_symbol_aliases=frozenset(state.external_symbol_aliases),
            external_module_aliases=frozenset(state.external_module_aliases),
            local_top_level_names=local_top_level_names,
        )
        if not base_names:
            continue
        base_names_by_class.append((class_qualname, base_names))
        if has_unresolved_external_base:
            unresolved_external.add(class_qualname)
    return (
        tuple(sorted(base_names_by_class, key=lambda item: item[0])),
        frozenset(unresolved_external),
    )


def _class_base_facts_for_node(
    class_node: ast.ClassDef,
    *,
    external_symbol_aliases: frozenset[str],
    external_module_aliases: frozenset[str],
    local_top_level_names: frozenset[str],
) -> tuple[tuple[str, ...], bool]:
    """One class's sorted base names, and whether a base escapes the root.

    The one rule for module-level and function-local classes alike, so a
    nested class is governed by rule 3 under exactly the opacity doctrine
    its module-level twin is.
    """
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
        if root_name in external_symbol_aliases or root_name in external_module_aliases:
            has_unresolved_external_base = True
    return tuple(sorted(base_names)), has_unresolved_external_base


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
    *,
    proven_roots: frozenset[str] = frozenset(),
) -> bool:
    """Whether a decorator expression IS a proven hook marker alias.

    Exact-name equality after unwrapping a decorator call, so ``@hookspec``
    and ``@hookimpl(tryfirst=True)`` both fire while an attribute path rooted
    at a marker alias does not - the proof covers the marker object itself,
    nothing reached through it.

    The alias map proves what a MODULE-LEVEL assignment bound; ``proven_roots``
    proves that this decorator's name still binds that object where the
    decorator is written. Both halves are required: the map alone let a
    parameter spelling the marker's name root the definition it decorated.
    """
    if not hook_marker_aliases:
        return False
    return any(
        _decorator_expr_name(decorator) in hook_marker_aliases & proven_roots
        for decorator in node.decorator_list
    )


def _has_external_decorator(
    node: _qualnames.FunctionNode,
    *,
    external_symbol_aliases: frozenset[str],
    external_module_aliases: frozenset[str],
    local_top_level_names: frozenset[str],
    proven_roots: frozenset[str] = frozenset(),
) -> bool:
    """Whether an import this analyzer cannot follow decorates the definition.

    ``proven_roots`` is the binding half of the claim. The alias sets are
    module-wide facts about what an import resolved to; on their own they let
    any name that merely SPELLS an alias root a definition - measured on a
    nested definition whose decorator root was a parameter of the enclosing
    function, which was rooted live exactly as if the module alias had been
    used. The root must bind the module object here, not only elsewhere.
    """
    admissible = (proven_roots - local_top_level_names) & (
        external_symbol_aliases | external_module_aliases
    )
    return any(
        name is not None and name.partition(".")[0] in admissible
        for decorator in node.decorator_list
        if (name := _decorator_expr_name(decorator)) is not None
    )


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
    #: The names this module's static ``__all__`` declares, as
    #: ``<module>:<name>`` - the declaring module's namespace path, whether or
    #: not anything defines that name here. A declaration fact beside the
    #: binding fact above: the exposure owner reads it to tell a public plain
    #: module's re-export (an import it lists) from an implementation detail
    #: (an import it does not), and to name what a module-level
    #: ``__getattr__`` serves. Never a reference.
    declared_exports: frozenset[str]
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
    #: Liveness policy v5: every definition under a function scope, and the
    #: alias facts the nested population's own rules read (the module walk
    #: state stays private to the walk; these are its relevant projections).
    nested_declarations: tuple[_NestedDeclaration, ...]
    external_symbol_aliases: frozenset[str]
    external_module_aliases: frozenset[str]
    hook_marker_aliases: frozenset[str]
    local_top_level_names: frozenset[str]
    #: Liveness policy v5, same generation: ``(definition path, decorator
    #: root name)`` for every decorator whose root PROVABLY binds the
    #: module-level object the alias facts above describe. The alias sets say
    #: what an import resolved to; only this says the decorator's name still
    #: means that object where it is written.
    proven_decorator_roots: frozenset[tuple[str, str]]
    #: Liveness policy v5: module-local lexical path -> the proven
    #: opaque-escape flow of the definition's value, sorted.
    escape_witnesses: tuple[tuple[str, str], ...]


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
    # The lexical pass runs for every lane: the nested population is
    # discovered in a test file too (and then judged non-actionable by its
    # lane, exactly like a module-level test definition), while the
    # reference facts are read only where references are collected at all.
    lexical = _collect_lexical_binding_facts(
        tree,
        settled_import_names=frozenset(state.internal_import_aliases),
        external_import_names=frozenset(
            state.external_symbol_aliases | state.external_module_aliases
        ),
    )
    if collect_referenced_names:
        state.referenced_names.update(lexical.unsettled_names)
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
            lexical_binding_paths=lexical.bound_definition_paths,
            import_bound_names=lexical.import_bound_names,
            import_bound_attributes=lexical.import_bound_attributes,
            definition_bound_attributes=lexical.definition_bound_attributes,
            proven_decorator_roots=lexical.proven_decorator_roots,
        )
        if collect_referenced_names
        else frozenset()
    )

    local_top_level_names = frozenset(
        {
            *(name for name, _node in collector.units if "." not in name),
            *(name for name, _node in collector.class_nodes if "." not in name),
        }
    )
    class_base_names, unresolved_external_base_classes = _collect_class_base_facts(
        collector=collector,
        state=state,
        local_top_level_names=local_top_level_names,
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
        declared_exports=frozenset(
            f"{module_name}:{name}" for name in state.exported_names
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
        nested_declarations=lexical.nested_declarations,
        external_symbol_aliases=frozenset(state.external_symbol_aliases),
        external_module_aliases=frozenset(state.external_module_aliases),
        hook_marker_aliases=_resolve_hook_marker_aliases(state),
        local_top_level_names=local_top_level_names,
        proven_decorator_roots=lexical.proven_decorator_roots,
        escape_witnesses=tuple(sorted(lexical.escape_witnesses.items())),
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


def _collect_nested_definitions(
    *,
    filepath: str,
    module_name: str,
    declarations: Sequence[_NestedDeclaration],
    suppression_index: Mapping[SuppressionTargetKey, tuple[str, ...]],
    protocol_symbol_aliases: frozenset[str],
    protocol_module_aliases: frozenset[str],
    non_runtime_decorator_aliases: frozenset[str],
    pydantic_module_aliases: frozenset[str],
    external_symbol_aliases: frozenset[str],
    external_module_aliases: frozenset[str],
    hook_marker_aliases: frozenset[str],
    local_top_level_names: frozenset[str],
    self_dispatched_by_class: Mapping[str, frozenset[str]],
    escape_witnesses: Mapping[str, str] | None = None,
    proven_decorator_roots: frozenset[tuple[str, str]],
) -> tuple[NestedDefinition, ...]:
    """The nested population, judged by the rules its module-level twin gets.

    Every admission rule the module-level candidate builder applies is applied
    here by the same predicate: a Protocol class and its members never become
    candidates, a non-runtime decorator (``@overload``, ``@abstractmethod``, a
    pydantic hook) keeps a function out, an external decorator or a proven
    hook marker roots one, a directive silences one. The rule-3 facts a
    nested method needs ride its own row, since no ``ClassMetrics`` row
    exists for a function-local class to carry them.
    """
    protocol_class_paths: set[str] = set()
    base_facts_by_class: dict[str, tuple[tuple[str, ...], bool]] = {}
    witnesses: Mapping[str, str] = escape_witnesses if escape_witnesses else {}
    for declaration in declarations:
        if not isinstance(declaration.node, ast.ClassDef):
            continue
        if _is_protocol_class(
            declaration.node,
            protocol_symbol_aliases=protocol_symbol_aliases,
            protocol_module_aliases=protocol_module_aliases,
        ):
            protocol_class_paths.add(declaration.path)
        base_facts_by_class[declaration.path] = _class_base_facts_for_node(
            declaration.node,
            external_symbol_aliases=external_symbol_aliases,
            external_module_aliases=external_module_aliases,
            local_top_level_names=local_top_level_names,
        )

    rows: list[NestedDefinition] = []
    for declaration in declarations:
        span = _node_line_span(declaration.node)
        if span is None:
            continue
        live_root_reason: _LocalLivenessRootReason | None = None
        owner_base_names: tuple[str, ...] = ()
        owner_has_unresolved_external_base = False
        decorator_evidenced = False
        self_dispatched = False
        if isinstance(declaration.node, ast.ClassDef):
            if declaration.path in protocol_class_paths:
                continue
        else:
            if declaration.parent_path in protocol_class_paths:
                continue
            if _is_non_runtime_candidate(
                declaration.node,
                non_runtime_decorator_aliases=non_runtime_decorator_aliases,
                pydantic_module_aliases=pydantic_module_aliases,
            ):
                continue
            if _external_decorator_roots_function(
                declaration.node,
                external_symbol_aliases=external_symbol_aliases,
                external_module_aliases=external_module_aliases,
                local_top_level_names=local_top_level_names,
                hook_marker_aliases=hook_marker_aliases,
                overload_aliases=non_runtime_decorator_aliases,
                proven_roots=proven_roots_for(
                    proven_decorator_roots, declaration.path
                ),
            ):
                live_root_reason = LIVENESS_EXTERNAL_DECORATOR
            if declaration.kind == "method":
                owner_base_names, owner_has_unresolved_external_base = (
                    base_facts_by_class.get(declaration.parent_path, ((), False))
                )
                decorator_evidenced = any(
                    _decorator_evidence_marker(decorator) is not None
                    for decorator in declaration.node.decorator_list
                )
                self_dispatched = declaration.node.name in self_dispatched_by_class.get(
                    declaration.parent_path, frozenset()
                )
        start, end = span
        qualname = f"{module_name}:{declaration.path}"
        rows.append(
            NestedDefinition(
                qualname=qualname,
                local_name=declaration.node.name,
                kind=declaration.kind,
                lexical_parent=f"{module_name}:{declaration.parent_path}",
                lexical_path=declaration.path,
                filepath=filepath,
                start_line=start,
                end_line=end,
                suppressed_rules=suppression_index.get(
                    suppression_target_key(
                        filepath=filepath,
                        qualname=qualname,
                        start_line=start,
                        end_line=end,
                        kind=declaration.kind,
                    ),
                    (),
                ),
                live_root_reason=live_root_reason,
                owner_base_names=owner_base_names,
                owner_has_unresolved_external_base=owner_has_unresolved_external_base,
                decorator_evidenced=decorator_evidenced,
                self_dispatched=self_dispatched,
                escape_witness=witnesses.get(declaration.path),
            )
        )
    return tuple(
        sorted(
            rows,
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
    nested_declarations: Sequence[_NestedDeclaration] = (),
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
    # A directive on a function-local definition binds exactly as one on its
    # module-level twin does: the nested population entered the lane, so the
    # local policy that silences a member of the lane reaches it too.
    declaration_specs.extend(
        (declaration.path, declaration.node, declaration.kind)
        for declaration in nested_declarations
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
    nested_declarations: Sequence[_NestedDeclaration] = (),
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
        nested_declarations=nested_declarations,
    )
    suppression_bindings = bind_suppressions_to_declarations(
        directives=suppression_directives,
        declarations=declaration_targets,
    )
    return build_suppression_index(suppression_bindings)
