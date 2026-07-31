# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ..metrics.class_facts import _class_methods, collect_class_walk_facts
from ..metrics.cohesion import _resolve_lcom4, cohesion_risk
from ..metrics.coupling import _resolve_cbo, coupling_risk
from ..models import ClassMetrics

if TYPE_CHECKING:
    from collections.abc import Mapping


def _node_line_span(node: ast.AST) -> tuple[int, int] | None:
    start = int(getattr(node, "lineno", 0))
    end = int(getattr(node, "end_lineno", 0))
    if start <= 0 or end <= 0:
        return None
    return start, end


def _self_dispatched_methods(
    method_calls: dict[str, set[str]],
    *,
    module_name: str,
    class_qualname: str,
) -> tuple[str, ...]:
    """Qualify the walk's self-call targets for the rule-3 decision table.

    The walk records ``self.<name>()`` only when ``<name>`` is itself a method
    of the class being walked, so the callee set needs no further filtering:
    an unrelated class's self-call can never appear here. Qualifying the names
    with the module prefix makes them comparable to ``DeadCandidate.qualname``.

    Methods excluded from the cohesion walk are absent from ``method_calls``
    and therefore never recorded as dispatched. That direction is deliberate:
    a missing fact abstains, it never claims liveness without evidence.
    """
    return tuple(
        sorted(
            {
                f"{module_name}:{class_qualname}.{callee}"
                for callees in method_calls.values()
                for callee in callees
            }
        )
    )


def _class_metrics_for_node(
    *,
    module_name: str,
    class_qualname: str,
    class_node: ast.ClassDef,
    filepath: str,
    imported_binding_names: set[str],
    imported_symbol_targets: Mapping[str, str],
    imported_module_targets: Mapping[str, str],
    module_class_names: set[str],
    cohesion_ignored_methods: frozenset[str] = frozenset(),
) -> ClassMetrics | None:
    span = _node_line_span(class_node)
    if span is None:
        return None
    start, end = span
    facts = collect_class_walk_facts(
        class_node,
        analyzed_method_names=frozenset(
            method.name
            for method in _class_methods(class_node)
            if method.name not in cohesion_ignored_methods
        ),
        imported_symbol_targets=imported_symbol_targets,
        imported_module_targets=imported_module_targets,
    )
    cbo, coupled_classes = _resolve_cbo(
        facts.couplings,
        facts.typed_couplings,
        class_name=class_node.name,
        module_class_names=module_class_names,
        imported_binding_names=imported_binding_names,
    )
    lcom4, method_count, instance_var_count = _resolve_lcom4(facts)
    return ClassMetrics(
        qualname=f"{module_name}:{class_qualname}",
        filepath=filepath,
        start_line=start,
        end_line=end,
        cbo=cbo,
        lcom4=lcom4,
        method_count=method_count,
        instance_var_count=instance_var_count,
        risk_coupling=coupling_risk(cbo),
        risk_cohesion=cohesion_risk(lcom4),
        coupled_classes=coupled_classes,
        instantiation_candidates=tuple(sorted(facts.instantiation_candidates)),
        self_dispatched_methods=_self_dispatched_methods(
            facts.method_calls,
            module_name=module_name,
            class_qualname=class_qualname,
        ),
    )
