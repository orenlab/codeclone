# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Lexical scope graph behind binding-aware wire emission (39Y-FP).

The wire emitter asks one question of this module — *what does this name
denote here* — and gets exactly one of six answers per name per scope:

``SELF`` / ``CLS``
    the receiver parameter of an instance or class method, matched by the
    name it is actually bound to rather than by the strings ``self``/``cls``.
``LOCAL``
    a binding created inside the scope by any binding form.
``IMPORT``
    a binding created by an import statement whose canonical dotted identity
    is proven, so ``import json as j`` and ``from json import dumps`` name the
    same symbol as ``json.dumps``.
``GLOBAL_LITERAL``
    a module-scope binding, a shadowed import alias, or a name with no binding
    anywhere (builtins land here). Emitted literally: the identity is unknown,
    so two different unknown names must never be merged.
``FREE``
    not a role of its own — a free name inherits the role resolved by the
    nearest enclosing function scope, which is why a captured ``self`` stays
    ``SELF`` and a captured clean import keeps its identity.

Two properties are deliberate and load-bearing:

*Scope-aware collection.* The collector never descends into a nested function,
lambda, class or comprehension body while gathering bindings for the current
scope. A plain ``ast.walk`` would poison the outer scope with inner names —
the defect this structure exists to prevent.

*Flow-insensitive shadowing.* One role per name per scope. A name bound both by
an import and by an assignment degrades for the whole scope, regardless of
statement order. Flow-sensitive roles would be a hidden heuristic; degrading is
deterministic, explainable, and conservative — a shadowed name falls toward
``LOCAL``/``GLOBAL_LITERAL``, never toward a wrong identity.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Final, Literal

from ..models import BindingSite, SymbolRole

__all__ = [
    "EMPTY_BINDINGS",
    "Binding",
    "BindingContext",
    "BindingSite",
    "FromImportTargetResolver",
    "SymbolRole",
    "build_module_bindings",
]

_ScopeKind = Literal["module", "function", "lambda", "class", "comprehension"]

#: Resolves an ``ImportFrom`` node to its absolute dotted module target, or
#: ``None`` when the target cannot be proven. Relative imports depend on the
#: importing module's package position, which lives outside this module — the
#: caller supplies that context so the scope graph itself stays a pure function
#: of the parsed tree plus this one resolver.
FromImportTargetResolver = Callable[[ast.ImportFrom], str | None]

_COMPREHENSION_TYPES: Final = (
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@dataclass(frozen=True, slots=True)
class Binding:
    """What one name denotes in one scope."""

    role: SymbolRole
    identity: str = ""


_SELF_BINDING: Final = Binding(role="self")
_CLS_BINDING: Final = Binding(role="cls")
_LOCAL_BINDING: Final = Binding(role="local")
_GLOBAL_LITERAL_BINDING: Final = Binding(role="global_literal")


@dataclass(frozen=True, slots=True)
class _Scope:
    """One resolved lexical scope.

    References point upward only (``parent``, ``module``), so the graph is
    acyclic and every node can stay frozen. Downward navigation is served by
    the node-keyed map on :class:`BindingContext`.
    """

    kind: _ScopeKind
    bindings: Mapping[str, Binding]
    parent: _Scope | None
    module: _Scope | None
    global_names: frozenset[str]
    nonlocal_names: frozenset[str]
    # Deterministic per-module scope number, assigned in depth-first
    # resolution order. Purely additive identity metadata: nothing in wire
    # emission reads it, so fp3 digests cannot depend on it.
    token: int = 0

    def _module_scope(self) -> _Scope:
        return self.module if self.module is not None else self

    def lookup(self, name: str) -> Binding | None:
        """Resolve ``name`` through the enclosing-scope chain."""

        hit = self._lookup_with_scope(name)
        return hit[0] if hit is not None else None

    def lookup_site(self, name: str) -> BindingSite | None:
        """Resolve ``name`` and report which scope answered.

        One resolution algorithm for both questions: ``lookup`` and this
        method share ``_lookup_with_scope``, so "what does this name denote"
        and "where is it bound" can never drift apart.
        """

        hit = self._lookup_with_scope(name)
        if hit is None:
            return None
        binding, scope = hit
        return BindingSite(
            role=binding.role,
            identity=binding.identity,
            scope_token=scope.token,
        )

    def _lookup_with_scope(self, name: str) -> tuple[Binding, _Scope] | None:
        if name in self.global_names:
            # A `global` declaration resolves against module scope, never
            # against an enclosing function.
            module_scope = self._module_scope()
            binding = module_scope.bindings.get(name)
            if binding is None:
                return None
            return binding, module_scope
        scope: _Scope | None = self
        if name in self.nonlocal_names:
            scope = self.parent
        while scope is not None:
            binding = scope.bindings.get(name)
            if binding is not None:
                return binding, scope
            scope = scope.parent
        return None


@dataclass(frozen=True, slots=True)
class BindingContext:
    """A cursor into one module's scope graph, positioned at one scope."""

    _scope: _Scope
    _scopes: Mapping[ast.AST, _Scope]

    def lookup(self, name: str) -> Binding | None:
        return self._scope.lookup(name)

    def lookup_site(self, name: str) -> BindingSite | None:
        return self._scope.lookup_site(name)

    def enter(self, node: ast.AST) -> BindingContext:
        """Return the context for a scope-introducing node's own body.

        Falls back to ``self`` when the node carries no scope, which keeps the
        emitter total: a synthesized node that never went through the collector
        is emitted under the scope it appears in rather than crashing.
        """

        scope = self._scopes.get(node)
        if scope is None:
            return self
        return BindingContext(_scope=scope, _scopes=self._scopes)


_EMPTY_SCOPE: Final = _Scope(
    kind="module",
    bindings={},
    parent=None,
    module=None,
    global_names=frozenset(),
    nonlocal_names=frozenset(),
)

#: Context for callers that emit a wire with no binding evidence at all — a
#: synthesized projection, or an annotation hashed on its own. Every name
#: resolves to ``GLOBAL_LITERAL`` and is preserved literally, because "no
#: evidence" must never be reported as "proven local".
EMPTY_BINDINGS: Final = BindingContext(_scope=_EMPTY_SCOPE, _scopes={})


@dataclass(slots=True)
class _DraftBindings:
    """What one scope binds, accumulated during collection and resolved here.

    Kept apart from the scope tree on purpose: a scope's *names* and a scope's
    *position among other scopes* are two different subjects, and folding both
    into one object left every accumulator method touching a different field.
    """

    imports: dict[str, str] = field(default_factory=dict)
    plain: set[str] = field(default_factory=set)
    global_names: set[str] = field(default_factory=set)
    nonlocal_names: set[str] = field(default_factory=set)
    self_name: str | None = None
    cls_name: str | None = None

    def bind_plain(self, name: str) -> None:
        self.plain.add(name)

    def bind_import(self, name: str, identity: str) -> None:
        self.imports[name] = identity

    def declare_global(self, names: Iterable[str]) -> None:
        self.global_names.update(names)

    def declare_nonlocal(self, names: Iterable[str]) -> None:
        self.nonlocal_names.update(names)

    def globals_written_here(self) -> set[str]:
        """Names declared global in this scope AND assigned in it."""

        return self.global_names & self.plain

    def resolve(self, plain_role: Binding) -> Mapping[str, Binding]:
        """Collapse the accumulated names into one role per name."""

        bindings: dict[str, Binding] = {}
        for name, identity in self.imports.items():
            # Flow-insensitive: a competing binding anywhere in the scope costs
            # the alias its identity for the whole scope.
            bindings[name] = (
                plain_role
                if name in self.plain
                else Binding(role="import", identity=identity)
            )
        for name in self.plain:
            bindings.setdefault(name, plain_role)
        if self.self_name is not None:
            bindings[self.self_name] = _SELF_BINDING
        if self.cls_name is not None:
            bindings[self.cls_name] = _CLS_BINDING
        for name in self.global_names | self.nonlocal_names:
            # Declared names are not own bindings: lookup redirects them to the
            # module scope or the enclosing function scope.
            bindings.pop(name, None)
        return bindings


@dataclass(slots=True)
class _ScopeDraft:
    """One node of the scope tree while it is still being collected."""

    kind: _ScopeKind
    node: ast.AST | None
    parent: _ScopeDraft | None
    bindings: _DraftBindings = field(default_factory=_DraftBindings)
    children: list[_ScopeDraft] = field(default_factory=list)

    def new_child(self, kind: _ScopeKind, node: ast.AST) -> _ScopeDraft:
        child = _ScopeDraft(kind=kind, node=node, parent=self)
        self.children.append(child)
        return child


def build_module_bindings(
    tree: ast.Module,
    *,
    resolve_from_import: FromImportTargetResolver,
) -> BindingContext:
    """Build the scope graph for one module and return its module-scope cursor."""

    root = _ScopeDraft(kind="module", node=tree, parent=None)
    _collect(tree.body, root, resolve_from_import)
    _propagate_global_writes(root)
    scopes: dict[ast.AST, _Scope] = {}
    module_scope = _resolve_draft(
        root,
        parent=None,
        module=None,
        scopes=scopes,
        tokens=count(),
    )
    return BindingContext(_scope=module_scope, _scopes=scopes)


# ---------------------------------------------------------------- collection


def _collect(
    nodes: Iterable[ast.AST],
    scope: _ScopeDraft,
    resolve: FromImportTargetResolver,
) -> None:
    for node in nodes:
        _collect_node(node, scope, resolve)


def _collect_node(
    node: ast.AST,
    scope: _ScopeDraft,
    resolve: FromImportTargetResolver,
) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scope.bindings.bind_plain(node.name)
        _collect(node.decorator_list, scope, resolve)
        _collect_signature_context(node.args, scope, resolve)
        if node.returns is not None:
            _collect_node(node.returns, scope, resolve)
        child = scope.new_child("function", node)
        _bind_parameters(node.args, child)
        _collect(node.body, child, resolve)
        return
    if isinstance(node, ast.Lambda):
        _collect_signature_context(node.args, scope, resolve)
        child = scope.new_child("lambda", node)
        _bind_parameters(node.args, child)
        _collect_node(node.body, child, resolve)
        return
    if isinstance(node, ast.ClassDef):
        scope.bindings.bind_plain(node.name)
        _collect(node.bases, scope, resolve)
        _collect(node.keywords, scope, resolve)
        _collect(node.decorator_list, scope, resolve)
        child = scope.new_child("class", node)
        _collect(node.body, child, resolve)
        return
    if isinstance(node, _COMPREHENSION_TYPES):
        _collect_comprehension(node, scope, resolve)
        return
    if isinstance(node, ast.Import):
        for alias in node.names:
            bound = alias.asname or alias.name.partition(".")[0]
            identity = alias.name if alias.asname else alias.name.partition(".")[0]
            scope.bindings.bind_import(bound, identity)
        return
    if isinstance(node, ast.ImportFrom):
        _collect_import_from(node, scope, resolve)
        return
    if isinstance(node, ast.Global):
        scope.bindings.declare_global(node.names)
        return
    if isinstance(node, ast.Nonlocal):
        scope.bindings.declare_nonlocal(node.names)
        return
    if isinstance(node, ast.NamedExpr):
        if isinstance(node.target, ast.Name):
            _walrus_target_scope(scope).bindings.bind_plain(node.target.id)
        _collect_node(node.value, scope, resolve)
        return
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            scope.bindings.bind_plain(node.id)
        return
    if (isinstance(node, ast.ExceptHandler) and node.name) or (
        isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name
    ):
        scope.bindings.bind_plain(node.name)
    elif isinstance(node, ast.MatchMapping) and node.rest:
        scope.bindings.bind_plain(node.rest)
    _collect(ast.iter_child_nodes(node), scope, resolve)


def _collect_comprehension(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    scope: _ScopeDraft,
    resolve: FromImportTargetResolver,
) -> None:
    generators = node.generators
    # The leftmost iterable is evaluated in the enclosing scope; everything
    # else — targets, conditions, later iterables, the element expression —
    # belongs to the comprehension's own scope.
    if generators:
        _collect_node(generators[0].iter, scope, resolve)
    child = scope.new_child("comprehension", node)
    for index, generator in enumerate(generators):
        _collect_node(generator.target, child, resolve)
        if index:
            _collect_node(generator.iter, child, resolve)
        _collect(generator.ifs, child, resolve)
    for element in _comprehension_elements(node):
        _collect_node(element, child, resolve)


def _comprehension_elements(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.DictComp):
        return (node.key, node.value)
    return (node.elt,)


def _collect_import_from(
    node: ast.ImportFrom,
    scope: _ScopeDraft,
    resolve: FromImportTargetResolver,
) -> None:
    target = resolve(node)
    for alias in node.names:
        if alias.name == "*":
            # A star import binds names this analysis cannot enumerate; it
            # creates no binding rather than a guessed one.
            continue
        bound = alias.asname or alias.name
        if target:
            scope.bindings.bind_import(bound, f"{target}.{alias.name}")
        else:
            # An unresolved relative import binds a name with no provable
            # identity. It stays a literal rather than being canonicalized
            # against a guess or erased to a variable.
            scope.bindings.bind_plain(bound)


def _collect_signature_context(
    args: ast.arguments,
    scope: _ScopeDraft,
    resolve: FromImportTargetResolver,
) -> None:
    """Collect the parts of a signature evaluated in the *enclosing* scope."""

    for default in (*args.defaults, *args.kw_defaults):
        if default is not None:
            _collect_node(default, scope, resolve)
    for argument in _all_args(args):
        if argument.annotation is not None:
            _collect_node(argument.annotation, scope, resolve)


def _all_args(args: ast.arguments) -> tuple[ast.arg, ...]:
    optional = (args.vararg, args.kwarg)
    return (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *(argument for argument in optional if argument is not None),
    )


def _bind_parameters(args: ast.arguments, scope: _ScopeDraft) -> None:
    for argument in _all_args(args):
        scope.bindings.bind_plain(argument.arg)


def _propagate_global_writes(root: _ScopeDraft) -> None:
    """Fold ``global x; x = ...`` writes into the module scope.

    A function that declares a name global and then assigns it shadows the
    module binding just as a module-level assignment does, so an import alias
    written through `global` loses its identity everywhere.
    """

    for scope in _iter_drafts(root):
        if scope is root:
            continue
        for name in scope.bindings.globals_written_here():
            root.bindings.bind_plain(name)


def _iter_drafts(root: _ScopeDraft) -> Iterable[_ScopeDraft]:
    stack = [root]
    while stack:
        scope = stack.pop()
        yield scope
        stack.extend(scope.children)


# ---------------------------------------------------------------- resolution


def _resolve_draft(
    draft: _ScopeDraft,
    *,
    parent: _Scope | None,
    module: _Scope | None,
    scopes: dict[ast.AST, _Scope],
    tokens: Iterator[int],
) -> _Scope:
    resolution_parent = _resolution_parent(parent)
    _classify_receiver(draft, class_scope=parent)
    plain_role = _GLOBAL_LITERAL_BINDING if draft.kind == "module" else _LOCAL_BINDING
    scope = _Scope(
        kind=draft.kind,
        bindings=draft.bindings.resolve(plain_role),
        parent=resolution_parent,
        module=module,
        global_names=frozenset(draft.bindings.global_names),
        nonlocal_names=frozenset(draft.bindings.nonlocal_names),
        # Depth-first resolution order is a pure function of the parsed tree,
        # so the token is as deterministic as the scope graph itself.
        token=next(tokens),
    )
    if draft.node is not None:
        scopes[draft.node] = scope
    module_scope = module if module is not None else scope
    for child in draft.children:
        _resolve_draft(
            child,
            parent=scope,
            module=module_scope,
            scopes=scopes,
            tokens=tokens,
        )
    return scope


def _resolution_parent(parent: _Scope | None) -> _Scope | None:
    """Skip class scopes: a class body is not part of the closure chain."""

    scope = parent
    while scope is not None and scope.kind == "class":
        scope = scope.parent
    return scope


def _walrus_target_scope(scope: _ScopeDraft) -> _ScopeDraft:
    """Return the scope a named expression binds in.

    A walrus inside a comprehension binds in the enclosing function scope, not
    in the comprehension — Python's rule, and the difference between
    ``[x for x in items]`` (leaks nothing) and ``[(x := i) for i in items]``
    (leaks ``x``).
    """

    while scope.kind == "comprehension" and scope.parent is not None:
        scope = scope.parent
    return scope


def _classify_receiver(draft: _ScopeDraft, *, class_scope: _Scope | None) -> None:
    if draft.kind != "function" or class_scope is None or class_scope.kind != "class":
        return
    node = draft.node
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return
    receiver = _first_positional_name(node.args)
    if receiver is None:
        return
    decorators = _builtin_decorator_names(node.decorator_list, class_scope)
    if "staticmethod" in decorators:
        return
    if "classmethod" in decorators:
        draft.bindings.cls_name = receiver
        return
    draft.bindings.self_name = receiver


def _first_positional_name(args: ast.arguments) -> str | None:
    positional = (*args.posonlyargs, *args.args)
    return positional[0].arg if positional else None


def _builtin_decorator_names(
    decorators: Sequence[ast.expr],
    class_scope: _Scope,
) -> frozenset[str]:
    """Return decorator names proven to be the builtins of those names.

    Resolution happens in the DEFINING scope — the class body, where the
    decorator expression is actually evaluated — so a local variable named
    ``classmethod`` inside the method cannot change how the method is
    classified. A name that resolves to any binding at all is not the builtin.
    """

    names: set[str] = set()
    for decorator in decorators:
        if not isinstance(decorator, ast.Name):
            continue
        if decorator.id not in {"classmethod", "staticmethod"}:
            continue
        if class_scope.lookup(decorator.id) is None:
            names.add(decorator.id)
    return frozenset(names)
