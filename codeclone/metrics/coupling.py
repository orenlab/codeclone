# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Coupling-between-objects (CBO) and its declared edge contract.

CBO EDGE CONTRACT
=================

A class's CBO is the number of DISTINCT collaborator names it references,
counted from exactly two edge lanes:

1. **Local lane.** A name that resolves to another class defined in the SAME
   module, referenced anywhere inside the class body. The referent is provably
   a class — its ``ClassDef`` was analyzed in this module — so every reference
   position counts.

2. **Imported-domain lane.** A name bound by an ``import`` statement of the
   same module, referenced in an *annotation* — parameter, return, attribute
   or variable, including names nested in subscripts, unions and tuples. An
   annotation position entails that the referent is a type, so the position
   itself is the evidence and no resolution is required.

   Base classes are NOT imported-domain edges. A local base is already counted
   by lane 1, and imported inheritance is carried by its own facts
   (``ClassMetrics.base_names``, ``has_unresolved_external_base``); counting it
   here would make every typing construct used as a base (``Protocol``,
   ``Generic``, ``TypedDict``, ``Enum``) a collaborator.

3. **Resolved instantiation lane.** A call whose callee is an imported binding
   is an edge only when that binding provably resolves to a class analyzed in
   this project. ``Call.func`` is a *position*, not evidence: ``handler()``,
   ``decorate()`` and ``Widget()`` are the same syntax, and only resolution
   separates a constructor from a function call. The per-file walk therefore
   emits candidates (``label|module:symbol``, the binding resolved to its
   import target) and the project-level fold in
   :func:`resolve_project_class_coupling` keeps a candidate only when its
   target appears in the project's class index. Both call forms are resolved:
   a bare ``Widget()`` through the symbol its ``from`` import binds, and a
   dotted ``module.Widget()`` through the module that binding names.

   The lane is deliberately silent rather than approximate: a callee that
   resolves to a function, to a decorator factory, or to a module outside the
   analysis root produces no edge. There is no capitalization rule and no
   name-shape rule — an unproven class is not a class.

Lanes 1 and 2 need no resolution because each already carries its own proof:
lane 1 knows the referent is a class of this module, lane 2 knows the position
entails a type. Lane 3 has neither, so it resolves or it abstains.

Never counted: builtins, ``self`` / ``cls``, the class's own name, and names
that resolve through no lane.

Declared limitations (honest opacity, not heuristics):

- string / forward-reference annotations are not parsed, so they carry no
  edges;
- a call target reached through more than one attribute hop
  (``pkg.mod.Widget()``) is not resolved, because the intermediate binding is
  not a name this module bound;
- an imported *module* binding yields an annotation edge only when the module
  name itself appears in a type position; ``os.getcwd()`` resolves the
  attribute (``getcwd``), never ``os``;
- an edge is labelled with the binding the source uses, so the same class
  imported under an alias is labelled by that alias. The label names the
  reference; the count is the metric, and it does not move under aliasing.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import replace
from typing import TYPE_CHECKING

from ..contracts import COUPLING_RISK_LOW_MAX, COUPLING_RISK_MEDIUM_MAX
from ._risk import RiskLevel, threshold_risk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import ClassMetrics

_BUILTIN_NAMES = frozenset(dir(builtins))

#: Separates a candidate's source-visible label from its resolved target.
#: Neither a Python identifier nor a module path can contain it, so the pack
#: is reversible.
CANDIDATE_SEPARATOR = "|"


def _annotation_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Tuple):
        for element in node.elts:
            candidate = _annotation_name(element)
            if candidate:
                return candidate
    return None


def _annotation_names(node: ast.AST | None) -> set[str]:
    """Return every symbol name appearing in a type expression.

    Unlike :func:`_annotation_name` this keeps the whole name set of the
    expression — ``dict[str, Order]`` yields ``{"dict", "str", "Order"}`` — so
    the imported-domain lane sees collaborators nested in subscripts, unions
    and tuples.
    """

    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Subscript):
        return _annotation_names(node.value) | _annotation_names(node.slice)
    if isinstance(node, ast.BinOp):
        return _annotation_names(node.left) | _annotation_names(node.right)
    if isinstance(node, ast.Tuple | ast.List):
        names: set[str] = set()
        for element in node.elts:
            names |= _annotation_names(element)
        return names
    return set()


def _resolve_cbo(
    couplings: frozenset[str],
    typed_couplings: frozenset[str],
    *,
    class_name: str,
    module_class_names: set[str],
    imported_binding_names: set[str],
) -> tuple[int, tuple[str, ...]]:
    """Count the two declared edge lanes (see the module edge contract)."""

    excluded = {"self", "cls", class_name}

    def _countable(name: str) -> bool:
        return bool(name) and name not in _BUILTIN_NAMES and name not in excluded

    local_edges = {
        name for name in couplings if _countable(name) and name in module_class_names
    }
    imported_edges = {
        name
        for name in typed_couplings
        if _countable(name) and name in imported_binding_names
    }
    resolved = tuple(sorted(local_edges | imported_edges))
    return len(resolved), resolved


def _resolved_candidate_labels(
    metric: ClassMetrics,
    *,
    class_index: frozenset[str],
) -> set[str]:
    """Return the labels of this class's candidates that name a real class."""

    own_name = metric.qualname.rpartition(":")[2].rpartition(".")[2]
    unpacked = (
        candidate.partition(CANDIDATE_SEPARATOR)
        for candidate in metric.instantiation_candidates
    )
    return {
        label
        for label, separator, target in unpacked
        if separator
        and target in class_index
        and label
        and label != own_name
        and label not in _BUILTIN_NAMES
    }


def resolve_project_class_coupling(
    class_metrics: Sequence[ClassMetrics],
) -> tuple[ClassMetrics, ...]:
    """Fold the resolved instantiation lane onto every class metric.

    Whether an imported callable is a class is a whole-project fact, so it is
    decided once, here, against the index of every analyzed class — never at
    file scope, where the answer is simply not available.

    Cold and warm runs agree because the candidates ride the cache on the
    class metric itself, so this fold sees the same input whether a file was
    analyzed or restored. That is the same property that makes export roots
    resolve identically on a warm run.

    Idempotent: candidates stay on the record and re-folding contributes the
    same labels to the same union.
    """

    class_index = frozenset(metric.qualname for metric in class_metrics)
    resolved: list[ClassMetrics] = []
    for metric in class_metrics:
        labels = _resolved_candidate_labels(metric, class_index=class_index)
        if not labels:
            resolved.append(metric)
            continue
        coupled = tuple(sorted(set(metric.coupled_classes) | labels))
        resolved.append(
            replace(
                metric,
                cbo=len(coupled),
                coupled_classes=coupled,
                risk_coupling=coupling_risk(len(coupled)),
            )
        )
    return tuple(resolved)


def coupling_risk(cbo: int) -> RiskLevel:
    return threshold_risk(
        cbo,
        low_max=COUPLING_RISK_LOW_MAX,
        medium_max=COUPLING_RISK_MEDIUM_MAX,
    )
