# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Instance-independent method detection for report-only design signals.

A method is *instance-independent* when it declares ``self`` but its executable
body never reads the instance receiver. This is a deterministic AST signal:
a method either loads its receiver binding or it does not. The interpretation
stays advisory — "does not read self" is **not** the same as "pure", and the
remediation language is always "review whether this belongs on the instance, as
a ``@staticmethod``, or as a module-level helper", never "convert to
``@staticmethod``".

The detector is bounded: Python AST only, one walk per method body, no import
execution, no type checker, no MRO resolution, and no framework heuristics.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ...domain.findings import (
    DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD,
    IIM_CLASSIFICATION_CANDIDATE,
    IIM_CLASSIFICATION_DECORATED_CONTEXT,
    IIM_CLASSIFICATION_DUNDER_PROTOCOL,
    IIM_CLASSIFICATION_INTERFACE_CONTRACT,
    IIM_CLASSIFICATION_NOOP_STUB,
    IIM_CLASSIFICATION_OVERRIDE_CONTEXT,
    IIM_CLASSIFICATION_PROPERTY_LIKE,
)

_RECEIVER_NAME = "self"

# Decorators that mean the method is not an instance method at all, or is an
# overload stub — never emitted as an instance-independent candidate.
_IGNORED_DECORATORS = frozenset({"staticmethod", "classmethod", "overload"})
_PROPERTY_DECORATORS = frozenset({"property", "setter", "deleter"})
_ABSTRACT_DECORATORS = frozenset({"abstractmethod", "abstractproperty"})
_OVERRIDE_DECORATORS = frozenset({"override"})
# Decorators that do not change the receiver-independence interpretation.
_KNOWN_SAFE_DECORATORS = frozenset({"final"})
_INTERFACE_BASE_NAMES = frozenset({"Protocol", "ABC"})
_INTERFACE_METACLASS_NAMES = frozenset({"ABCMeta"})

# Classification precedence: lower rank wins for mixed cases (e.g. an abstract
# property is property_like, a decorated dunder is dunder_protocol).
_CLASSIFICATION_RANK: dict[str, int] = {
    IIM_CLASSIFICATION_NOOP_STUB: 2,
    IIM_CLASSIFICATION_PROPERTY_LIKE: 3,
    IIM_CLASSIFICATION_DUNDER_PROTOCOL: 4,
    IIM_CLASSIFICATION_INTERFACE_CONTRACT: 5,
    IIM_CLASSIFICATION_OVERRIDE_CONTEXT: 6,
    IIM_CLASSIFICATION_DECORATED_CONTEXT: 7,
    IIM_CLASSIFICATION_CANDIDATE: 8,
}

_DEFAULT_CLASSIFICATIONS = frozenset({IIM_CLASSIFICATION_CANDIDATE})
_CONTEXT_CLASSIFICATIONS = frozenset(
    {
        IIM_CLASSIFICATION_INTERFACE_CONTRACT,
        IIM_CLASSIFICATION_OVERRIDE_CONTEXT,
        IIM_CLASSIFICATION_DECORATED_CONTEXT,
    }
)
_SUPPRESSED_CLASSIFICATIONS = frozenset(
    {
        IIM_CLASSIFICATION_PROPERTY_LIKE,
        IIM_CLASSIFICATION_DUNDER_PROTOCOL,
        IIM_CLASSIFICATION_NOOP_STUB,
    }
)

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True, slots=True)
class InstanceIndependentMethodOccurrence:
    """A single method that declares ``self`` but does not read instance state."""

    file_path: str
    class_qualname: str
    method_qualname: str
    method_name: str
    start: int
    end: int
    classification: str
    receiver_name: str
    decorators: tuple[str, ...]
    class_bases: tuple[str, ...]
    receiver_reads: int
    nested_receiver_reads: int


@dataclass(frozen=True, slots=True)
class DesignFindingSignature:
    """Aggregate counts for a design finding group."""

    candidate_count: int
    production_candidate_count: int
    test_candidate_count: int
    context_count: int
    suppressed_count: int


@dataclass(frozen=True, slots=True)
class DesignFindingGroup:
    """A per-class group of instance-independent method occurrences."""

    finding_kind: str
    finding_key: str
    file_path: str
    class_qualname: str
    class_bases: tuple[str, ...]
    signature: DesignFindingSignature
    items: tuple[InstanceIndependentMethodOccurrence, ...]


def _simple_decorator_name(node: ast.expr) -> str:
    """Last dotted component of a decorator expression.

    ``@staticmethod`` -> ``staticmethod``; ``@typing.override`` -> ``override``;
    ``@x.setter`` -> ``setter``; ``@functools.cache`` -> ``cache``.
    """
    target: ast.expr = node
    if isinstance(target, ast.Call):
        target = target.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _normalized_decorators(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...]:
    names = [
        name
        for name in (_simple_decorator_name(dec) for dec in method.decorator_list)
        if name
    ]
    return tuple(sorted(names))


def _simple_base_name(node: ast.expr) -> str:
    target: ast.expr = node
    if isinstance(target, ast.Subscript):
        target = target.value
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _class_base_names(class_node: ast.ClassDef) -> tuple[str, ...]:
    names = [
        name for name in (_simple_base_name(base) for base in class_node.bases) if name
    ]
    return tuple(names)


def _class_is_interface(class_node: ast.ClassDef, base_names: Sequence[str]) -> bool:
    if any(name in _INTERFACE_BASE_NAMES for name in base_names):
        return True
    for keyword in class_node.keywords:
        if keyword.arg == "metaclass":
            metaclass = _simple_base_name(keyword.value)
            if metaclass in _INTERFACE_METACLASS_NAMES:
                return True
    return False


def _first_positional_arg(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    positional = [*method.args.posonlyargs, *method.args.args]
    if not positional:
        return None
    return positional[0].arg


def _function_param_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> set[str]:
    args = func.args
    names = {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


class _ReceiverUseVisitor(ast.NodeVisitor):
    """Counts lexical reads of the outer method receiver.

    Descends into ``lambda`` and nested functions so a closure reading the outer
    ``self`` still proves instance dependence. A nested function whose own
    parameters shadow ``self`` masks the outer receiver for its subtree. Nested
    ``ClassDef`` bodies introduce a new receiver context and are not descended as
    outer-receiver evidence.
    """

    __slots__ = (
        "_depth",
        "_shadowed",
        "nested_receiver_reads",
        "receiver_reads",
    )

    def __init__(self) -> None:
        self._depth = 0
        self._shadowed = False
        self.receiver_reads = 0
        self.nested_receiver_reads = 0

    def _record_read(self) -> None:
        if self._depth == 0:
            self.receiver_reads += 1
        else:
            self.nested_receiver_reads += 1

    def visit_Name(self, node: ast.Name) -> None:
        if (
            node.id == _RECEIVER_NAME
            and isinstance(node.ctx, ast.Load)
            and not self._shadowed
        ):
            self._record_read()

    def visit_Call(self, node: ast.Call) -> None:
        # Direct method-body zero-arg ``super()`` depends on the receiver even
        # though the AST has no ``Name("self")``. Nested zero-arg ``super()`` is
        # not inferred as outer-receiver use without full compiler semantics.
        if (
            self._depth == 0
            and not self._shadowed
            and isinstance(node.func, ast.Name)
            and node.func.id == "super"
            and not node.args
            and not node.keywords
        ):
            self._record_read()
        self.generic_visit(node)

    def _visit_nested_callable(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    ) -> None:
        shadows = _RECEIVER_NAME in _function_param_names(node)
        previous_shadowed = self._shadowed
        self._depth += 1
        self._shadowed = previous_shadowed or shadows
        # Default values execute in the enclosing scope, not the nested body,
        # so visit them at the current (outer) shadow level by walking the
        # signature defaults before flipping into the nested body.
        try:
            self.generic_visit(node)
        finally:
            self._depth -= 1
            self._shadowed = previous_shadowed

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_callable(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_nested_callable(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # A nested class introduces a fresh receiver context. Its bases,
        # decorators, and keyword arguments still execute in the method body,
        # so scan those, but do not descend into its method bodies.
        for child in (*node.bases, *node.keywords, *node.decorator_list):
            self.visit(child)


def _count_receiver_usage(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[int, int]:
    visitor = _ReceiverUseVisitor()
    for statement in method.body:
        visitor.visit(statement)
    return visitor.receiver_reads, visitor.nested_receiver_reads


def _is_docstring_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_stub_statement(statement: ast.stmt) -> bool:
    """True for ``pass``, an ``...`` ellipsis expression, or ``NotImplementedError``."""
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return statement.value.value is Ellipsis
    if isinstance(statement, ast.Raise):
        return _raises_not_implemented(statement)
    return False


def _is_noop_stub(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [
        statement for statement in method.body if not _is_docstring_statement(statement)
    ]
    # A docstring-only body collapses to an empty list and counts as a stub.
    return all(_is_stub_statement(statement) for statement in body)


def _raises_not_implemented(statement: ast.Raise) -> bool:
    exc = statement.exc
    if exc is None:
        return False
    target: ast.expr = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def _classify_method(
    *,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    decorators: Sequence[str],
    class_is_interface: bool,
) -> str:
    decorator_set = set(decorators)
    candidates: list[str] = []

    if _is_noop_stub(method):
        candidates.append(IIM_CLASSIFICATION_NOOP_STUB)
    if decorator_set & _PROPERTY_DECORATORS:
        candidates.append(IIM_CLASSIFICATION_PROPERTY_LIKE)
    if _is_dunder(method.name):
        candidates.append(IIM_CLASSIFICATION_DUNDER_PROTOCOL)
    if class_is_interface or (decorator_set & _ABSTRACT_DECORATORS):
        candidates.append(IIM_CLASSIFICATION_INTERFACE_CONTRACT)
    if decorator_set & _OVERRIDE_DECORATORS:
        candidates.append(IIM_CLASSIFICATION_OVERRIDE_CONTEXT)

    classified_names = (
        _PROPERTY_DECORATORS
        | _ABSTRACT_DECORATORS
        | _OVERRIDE_DECORATORS
        | _KNOWN_SAFE_DECORATORS
    )
    if decorator_set - classified_names:
        candidates.append(IIM_CLASSIFICATION_DECORATED_CONTEXT)

    if not candidates:
        return IIM_CLASSIFICATION_CANDIDATE
    return min(candidates, key=lambda name: _CLASSIFICATION_RANK[name])


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _node_end_line(node: ast.AST, fallback: int) -> int:
    end = getattr(node, "end_lineno", None)
    if isinstance(end, int):
        return end
    return fallback


def _iter_class_defs(tree: ast.Module) -> Iterable[tuple[ast.ClassDef, str]]:
    """Yield every class with its dotted qualname (including nested classes)."""

    def walk(node: ast.AST, prefix: str) -> Iterable[tuple[ast.ClassDef, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                yield child, qualname
                yield from walk(child, f"{qualname}.")
            elif isinstance(child, _FUNCTION_NODES):
                yield from walk(child, f"{prefix}{child.name}.")

    yield from walk(tree, "")


def _direct_methods(
    class_node: ast.ClassDef,
) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for statement in class_node.body:
        if isinstance(statement, _FUNCTION_NODES):
            yield statement


def _occurrence_for_method(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    class_qualname: str,
    base_names: tuple[str, ...],
    class_is_interface: bool,
    file_path: str,
) -> InstanceIndependentMethodOccurrence | None:
    """Build an occurrence for a method, or ``None`` when it is not a candidate."""
    decorators = _normalized_decorators(method)
    if (
        _first_positional_arg(method) != _RECEIVER_NAME
        or set(decorators) & _IGNORED_DECORATORS
    ):
        return None
    receiver_reads, nested_receiver_reads = _count_receiver_usage(method)
    if receiver_reads or nested_receiver_reads:
        return None
    start = method.lineno
    return InstanceIndependentMethodOccurrence(
        file_path=file_path,
        class_qualname=class_qualname,
        method_qualname=f"{class_qualname}.{method.name}",
        method_name=method.name,
        start=start,
        end=_node_end_line(method, start),
        classification=_classify_method(
            method=method,
            decorators=decorators,
            class_is_interface=class_is_interface,
        ),
        receiver_name=_RECEIVER_NAME,
        decorators=decorators,
        class_bases=base_names,
        receiver_reads=receiver_reads,
        nested_receiver_reads=nested_receiver_reads,
    )


def collect_instance_independent_methods(
    *,
    tree: ast.Module,
    file_path: str,
) -> tuple[InstanceIndependentMethodOccurrence, ...]:
    """Collect instance-independent method occurrences for one module AST."""
    occurrences: list[InstanceIndependentMethodOccurrence] = []
    for class_node, class_qualname in _iter_class_defs(tree):
        base_names = _class_base_names(class_node)
        class_is_interface = _class_is_interface(class_node, base_names)
        for method in _direct_methods(class_node):
            occurrence = _occurrence_for_method(
                method,
                class_qualname=class_qualname,
                base_names=base_names,
                class_is_interface=class_is_interface,
                file_path=file_path,
            )
            if occurrence is not None:
                occurrences.append(occurrence)
    occurrences.sort(
        key=lambda item: (item.file_path, item.start, item.method_qualname)
    )
    return tuple(occurrences)


def _group_finding_key(file_path: str, class_qualname: str) -> str:
    payload = (
        f"design:{DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD}:v1\n"
        f"{file_path}\n{class_qualname}"
    )
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def group_instance_independent_methods(
    occurrences: Sequence[InstanceIndependentMethodOccurrence],
    *,
    test_paths: frozenset[str] = frozenset(),
) -> tuple[DesignFindingGroup, ...]:
    """Group occurrences by class and compute per-group signature counts.

    ``test_paths`` carries repo-relative paths classified as test source so the
    signature can split production vs test candidates without re-deriving
    source-kind policy here.
    """
    by_class: dict[tuple[str, str], list[InstanceIndependentMethodOccurrence]] = {}
    class_bases: dict[tuple[str, str], tuple[str, ...]] = {}
    for occurrence in occurrences:
        key = (occurrence.file_path, occurrence.class_qualname)
        by_class.setdefault(key, []).append(occurrence)
        class_bases.setdefault(key, occurrence.class_bases)

    groups: list[DesignFindingGroup] = []
    for (file_path, class_qualname), items in by_class.items():
        ordered = tuple(
            sorted(
                items,
                key=lambda item: (item.file_path, item.start, item.method_qualname),
            )
        )
        is_test = file_path in test_paths
        candidate_count = 0
        production_candidate_count = 0
        test_candidate_count = 0
        context_count = 0
        suppressed_count = 0
        for item in ordered:
            if item.classification in _DEFAULT_CLASSIFICATIONS:
                candidate_count += 1
                if is_test:
                    test_candidate_count += 1
                else:
                    production_candidate_count += 1
            elif item.classification in _CONTEXT_CLASSIFICATIONS:
                context_count += 1
            elif item.classification in _SUPPRESSED_CLASSIFICATIONS:
                suppressed_count += 1
        groups.append(
            DesignFindingGroup(
                finding_kind=DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD,
                finding_key=_group_finding_key(file_path, class_qualname),
                file_path=file_path,
                class_qualname=class_qualname,
                class_bases=class_bases[(file_path, class_qualname)],
                signature=DesignFindingSignature(
                    candidate_count=candidate_count,
                    production_candidate_count=production_candidate_count,
                    test_candidate_count=test_candidate_count,
                    context_count=context_count,
                    suppressed_count=suppressed_count,
                ),
                items=ordered,
            )
        )

    groups.sort(
        key=lambda group: (
            -group.signature.candidate_count,
            group.file_path,
            group.class_qualname,
            group.finding_key,
        )
    )
    return tuple(groups)


__all__ = [
    "DesignFindingGroup",
    "DesignFindingSignature",
    "InstanceIndependentMethodOccurrence",
    "collect_instance_independent_methods",
    "group_instance_independent_methods",
]
