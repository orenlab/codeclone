# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

from ..metrics import cohesion_risk, compute_cbo, compute_lcom4, coupling_risk
from ..models import ClassMetrics


def _node_line_span(node: ast.AST) -> tuple[int, int] | None:
    start = int(getattr(node, "lineno", 0))
    end = int(getattr(node, "end_lineno", 0))
    if start <= 0 or end <= 0:
        return None
    return start, end


def _class_metrics_for_node(
    *,
    module_name: str,
    class_qualname: str,
    class_node: ast.ClassDef,
    filepath: str,
    module_import_names: set[str],
    module_class_names: set[str],
) -> ClassMetrics | None:
    span = _node_line_span(class_node)
    if span is None:
        return None
    start, end = span
    cbo, coupled_classes = compute_cbo(
        class_node,
        module_import_names=module_import_names,
        module_class_names=module_class_names,
    )
    lcom4, method_count, instance_var_count = compute_lcom4(class_node)
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
    )
