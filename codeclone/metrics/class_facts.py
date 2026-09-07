# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ..models import ClassWalkFacts
from .coupling import CANDIDATE_SEPARATOR, _annotation_name, _annotation_names

if TYPE_CHECKING:
    from collections.abc import Mapping


def _class_methods(
    class_node: ast.ClassDef,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _add_coupling(couplings: set[str], node: ast.AST) -> None:
    candidate: str | None = None
    if isinstance(node, ast.Name):
        candidate = node.id
    elif isinstance(node, ast.Attribute):
        if not (isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}):
            candidate = node.attr
    elif isinstance(node, ast.Call):
        candidate = _annotation_name(node.func)
    elif isinstance(node, ast.AnnAssign | ast.arg):
        annotation = node.annotation
        if annotation is not None:
            candidate = _annotation_name(annotation)
    if candidate:
        couplings.add(candidate)


def _add_typed_coupling(typed_couplings: set[str], node: ast.AST) -> None:
    """Record names used in an annotation position.

    An annotation entails that its names are types, which is what lets the
    imported-domain lane count them without resolving the binding. A call
    target entails nothing of the sort and is handled by
    :func:`_add_instantiation_candidate`; see the edge contract in
    :mod:`codeclone.metrics.coupling`.
    """

    if isinstance(node, ast.AnnAssign | ast.arg):
        typed_couplings |= _annotation_names(node.annotation)
    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        typed_couplings |= _annotation_names(node.returns)


def _add_instantiation_candidate(
    candidates: set[str],
    node: ast.AST,
    *,
    imported_symbol_targets: Mapping[str, str],
    imported_module_targets: Mapping[str, str],
) -> None:
    """Record a call target that an import of this module bound.

    Two call forms carry a resolvable binding: ``Widget()``, where the ``from``
    import names the symbol directly, and ``mod.Widget()``, where the binding
    names the module the attribute is read from. Anything else — a call on a
    local variable, a deeper attribute chain, a subscript — binds nothing this
    module imported and is left alone.
    """

    if not isinstance(node, ast.Call):
        return
    func = node.func
    if isinstance(func, ast.Name):
        target = imported_symbol_targets.get(func.id)
        if target is not None:
            candidates.add(f"{func.id}{CANDIDATE_SEPARATOR}{target}")
        return
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        module = imported_module_targets.get(func.value.id)
        if module is not None:
            candidates.add(
                f"{func.attr}{CANDIDATE_SEPARATOR}{module}:{func.attr}",
            )


def _collect_method_node(
    *,
    node: ast.AST,
    method_name: str,
    method_to_attrs: dict[str, set[str]],
    method_calls: dict[str, set[str]],
) -> None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        method_to_attrs[method_name].add(node.attr)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr in method_calls
    ):
        method_calls[method_name].add(node.func.attr)


def _receiver_is_the_instance(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether ``self`` inside ``method`` provably binds the declaring class.

    Python binds the first parameter of an ordinary method to the instance;
    nothing binds the SPELLING ``self``. The three ways the spelling can mean
    something else are refused here:

    * a ``@staticmethod`` takes no receiver, so its first parameter is an
      ordinary value the caller supplied - and if it is named ``self``, every
      ``self.<name>()`` in its body is a call on an unknown object;
    * a method whose first parameter is named something else (``cls``, or a
      house style) leaves ``self`` free for any other binding;
    * a method that REBINDS ``self`` anywhere in its body no longer has one
      receiver for the flow-insensitive read this lane performs.

    Refusing is safe in this lane and only here: the method's own name is
    already a bare-name signal, so a refused dispatch abstains as
    ``ambiguous_internal_binding`` rather than being reported dead.
    """
    if any(
        _annotation_name(decorator) == "staticmethod"
        for decorator in method.decorator_list
    ):
        return False
    parameters = [*method.args.posonlyargs, *method.args.args]
    if not parameters or parameters[0].arg != "self":
        return False
    return not any(
        isinstance(node, ast.Name)
        and node.id == "self"
        and isinstance(node.ctx, ast.Store | ast.Del)
        for node in ast.walk(method)
    )


def _receiver_bound_nodes(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST]:
    """The nodes of ``method`` where ``self`` still binds ITS receiver.

    ``ast.walk`` descends through every nested function, lambda and class, and
    each of those can bind ``self`` again - a nested ``def inner(self)``, or a
    nested class whose own methods take their own receiver. Attributing their
    calls to the enclosing method's class is the containment claim this walk
    used to make without checking it. The traversal stops at any nested scope
    that rebinds the name; a nested scope that does NOT is still reading the
    enclosing receiver by closure, so it is kept.
    """
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = [method]
    seen = False
    while stack:
        node = stack.pop()
        if seen and _opens_its_own_receiver_scope(node):
            continue
        seen = True
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def _opens_its_own_receiver_scope(node: ast.AST) -> bool:
    """Whether ``self`` inside ``node`` is a DIFFERENT binding.

    A nested class always is: its methods take their own receiver. A nested
    function or lambda is one exactly when it declares a ``self`` parameter;
    one that does not still reads the enclosing receiver by closure.
    """

    if isinstance(node, ast.ClassDef):
        return True
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return False
    arguments = node.args
    return any(
        argument is not None and argument.arg == "self"
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        )
    )


def _is_self_method_call(
    node: ast.AST, method_calls: dict[str, set[str]]
) -> str | None:
    """The callee of a ``self.<name>()`` whose ``<name>`` is a method here."""

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr in method_calls
    ):
        return node.func.attr
    return None


def _collect_self_dispatched_calls(
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef],
    *,
    method_calls: dict[str, set[str]],
) -> dict[str, set[str]]:
    """The receiver-proven projection of ``method_calls`` (liveness policy v5).

    Read from the same nodes rather than collected beside them, so the proven
    lane can only ever be a SUBSET of what cohesion reads and LCOM's input is
    untouched by construction.
    """

    dispatched: dict[str, set[str]] = {name: set() for name in method_calls}
    for method in methods:
        if method.name not in dispatched or not _receiver_is_the_instance(method):
            continue
        for node in _receiver_bound_nodes(method):
            callee = _is_self_method_call(node, method_calls)
            if callee is not None:
                dispatched[method.name].add(callee)
    return dispatched


def collect_class_walk_facts(
    class_node: ast.ClassDef,
    *,
    analyzed_method_names: frozenset[str],
    imported_symbol_targets: Mapping[str, str],
    imported_module_targets: Mapping[str, str],
) -> ClassWalkFacts:
    """Collect coupling and cohesion inputs in one partitioned class walk."""
    couplings: set[str] = set()
    typed_couplings: set[str] = set()
    instantiation_candidates: set[str] = set()
    methods = _class_methods(class_node)
    method_to_attrs: dict[str, set[str]] = {
        method.name: set() for method in methods if method.name in analyzed_method_names
    }
    method_calls: dict[str, set[str]] = {name: set() for name in method_to_attrs}

    # Bases feed the LOCAL lane only (unchanged). They are deliberately not
    # imported-domain edges: external inheritance is already carried as its own
    # fact (ClassMetrics.base_names / has_unresolved_external_base), and
    # counting it here would turn every typing construct used as a base
    # (Protocol, Generic, TypedDict, Enum) into a collaborator.
    for base in class_node.bases:
        candidate = _annotation_name(base)
        if candidate:
            couplings.add(candidate)

    for child in ast.iter_child_nodes(class_node):
        method = (
            child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else None
        )
        for node in ast.walk(child):
            _add_coupling(couplings, node)
            _add_typed_coupling(typed_couplings, node)
            _add_instantiation_candidate(
                instantiation_candidates,
                node,
                imported_symbol_targets=imported_symbol_targets,
                imported_module_targets=imported_module_targets,
            )
            if method is not None and method.name in method_to_attrs:
                _collect_method_node(
                    node=node,
                    method_name=method.name,
                    method_to_attrs=method_to_attrs,
                    method_calls=method_calls,
                )

    return ClassWalkFacts(
        couplings=frozenset(couplings),
        typed_couplings=frozenset(typed_couplings),
        instantiation_candidates=frozenset(instantiation_candidates),
        method_to_attrs=method_to_attrs,
        method_calls=method_calls,
        self_dispatched_calls=_collect_self_dispatched_calls(
            methods, method_calls=method_calls
        ),
        all_method_count=len(methods),
    )


__all__ = ["collect_class_walk_facts"]
