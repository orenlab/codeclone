# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Coupling + Cohesion panel renderer (unified Quality tab)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _render_chain_flow
from .._components import Tone, insight_block
from .._tables import render_rows_table
from .._tabs import render_split_tabs
from ._coverage_join import (
    coverage_join_quality_count,
    coverage_join_quality_summary,
    render_coverage_join_panel,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _render_coupled_cell(row_data: Mapping[str, object]) -> str:
    raw = _as_sequence(row_data.get("coupled_classes"))
    names = sorted(
        {str(v).strip() for v in raw if isinstance(v, str) and str(v).strip()}
    )
    if not names:
        return "-"
    if len(names) <= 3:
        return _render_chain_flow(names)
    preview = _render_chain_flow(names[:3])
    full = _render_chain_flow(names)
    rem = len(names) - 3
    return (
        '<details class="coupled-details">'
        '<summary class="coupled-summary">'
        f'{preview}<span class="coupled-more">(+{rem} more)</span>'
        "</summary>"
        f'<div class="coupled-expanded">{full}</div>'
        "</details>"
    )


def render_quality_panel(ctx: ReportContext) -> str:
    """Build the unified Quality tab (Complexity + Coupling + Cohesion sub-tabs)."""
    coupling_summary = _as_mapping(ctx.coupling_map.get("summary"))
    cohesion_summary = _as_mapping(ctx.cohesion_map.get("summary"))
    complexity_summary = _as_mapping(ctx.complexity_map.get("summary"))
    overloaded_modules_summary = _as_mapping(ctx.overloaded_modules_map.get("summary"))
    coverage_join_summary = coverage_join_quality_summary(ctx)

    coupling_high_risk = _as_int(coupling_summary.get("high_risk"))
    cohesion_low = _as_int(cohesion_summary.get("low_cohesion"))
    complexity_high_risk = _as_int(complexity_summary.get("high_risk"))
    overloaded_module_candidates = _as_int(overloaded_modules_summary.get("candidates"))
    coverage_review_items = coverage_join_quality_count(ctx)
    coverage_hotspots = _as_int(coverage_join_summary.get("coverage_hotspots"))
    coverage_scope_gaps = _as_int(coverage_join_summary.get("scope_gap_hotspots"))
    coverage_join_status = str(coverage_join_summary.get("status", "")).strip()
    cc_max = _as_int(complexity_summary.get("max"))

    # Insight
    answer: str
    tone: Tone
    if not ctx.metrics_available:
        answer = "Metrics are skipped for this run."
        tone = "info"
    else:
        answer = (
            f"High-complexity: {complexity_high_risk}; "
            f"high-coupling: {coupling_high_risk}; "
            f"low-cohesion: {cohesion_low}; "
            f"overloaded modules: {overloaded_module_candidates}; "
            f"max CC {cc_max}; "
            f"max CBO {coupling_summary.get('max', 'n/a')}; "
            f"max LCOM4 {cohesion_summary.get('max', 'n/a')}."
        )
        if coverage_join_summary:
            if coverage_join_status == "ok":
                answer += (
                    f" Coverage hotspots: {coverage_hotspots}; "
                    f"scope gaps: {coverage_scope_gaps}."
                )
            else:
                answer += " Coverage join unavailable."
        if overloaded_module_candidates > 0 or (
            coupling_high_risk > 0 and cohesion_low > 0
        ):
            tone = "risk"
        elif (
            coupling_high_risk > 0
            or cohesion_low > 0
            or complexity_high_risk > 0
            or coverage_review_items > 0
        ):
            tone = "warn"
        else:
            tone = "ok"

    # Complexity sub-tab
    cx_rows_data = _as_sequence(ctx.complexity_map.get("functions"))
    cx_rows = [
        (
            ctx.bare_qualname(
                str(_as_mapping(r).get("qualname", "")),
                str(_as_mapping(r).get("filepath", "")),
            ),
            str(_as_mapping(r).get("filepath", "")),
            str(_as_mapping(r).get("cyclomatic_complexity", "")),
            str(_as_mapping(r).get("nesting_depth", "")),
            str(_as_mapping(r).get("risk", "")),
        )
        for r in cx_rows_data[:50]
    ]
    cx_panel = render_rows_table(
        headers=("Function", "File", "CC", "Nesting", "Risk"),
        rows=cx_rows,
        empty_message="Complexity metrics are not available.",
        ctx=ctx,
    )

    # Coupling sub-tab
    cp_rows_data = _as_sequence(ctx.coupling_map.get("classes"))
    cp_rows = [
        (
            ctx.bare_qualname(
                str(_as_mapping(r).get("qualname", "")),
                str(_as_mapping(r).get("filepath", "")),
            ),
            str(_as_mapping(r).get("filepath", "")),
            str(_as_mapping(r).get("cbo", "")),
            str(_as_mapping(r).get("risk", "")),
            _render_coupled_cell(_as_mapping(r)),
        )
        for r in cp_rows_data[:50]
    ]
    cp_panel = render_rows_table(
        headers=("Class", "File", "CBO", "Risk", "Coupled classes"),
        rows=cp_rows,
        empty_message="Coupling metrics are not available.",
        raw_html_headers=("Coupled classes",),
        ctx=ctx,
    )

    # Cohesion sub-tab
    ch_rows_data = _as_sequence(ctx.cohesion_map.get("classes"))
    ch_rows = [
        (
            ctx.bare_qualname(
                str(_as_mapping(r).get("qualname", "")),
                str(_as_mapping(r).get("filepath", "")),
            ),
            str(_as_mapping(r).get("filepath", "")),
            str(_as_mapping(r).get("lcom4", "")),
            str(_as_mapping(r).get("risk", "")),
            str(_as_mapping(r).get("method_count", "")),
            str(_as_mapping(r).get("instance_var_count", "")),
        )
        for r in ch_rows_data[:50]
    ]
    ch_panel = render_rows_table(
        headers=("Class", "File", "LCOM4", "Risk", "Methods", "Fields"),
        rows=ch_rows,
        empty_message="Cohesion metrics are not available.",
        ctx=ctx,
    )

    gm_rows_data = _as_sequence(ctx.overloaded_modules_map.get("items"))
    gm_rows = [
        (
            str(_as_mapping(r).get("module", "")),
            str(
                _as_mapping(r).get("relative_path")
                or _as_mapping(r).get("filepath")
                or ""
            ),
            str(_as_mapping(r).get("score", "")),
            str(_as_mapping(r).get("candidate_status", "")),
            str(_as_mapping(r).get("loc", "")),
            f"{_as_mapping(r).get('fan_in', '')}/{_as_mapping(r).get('fan_out', '')}",
            str(_as_mapping(r).get("complexity_total", "")),
        )
        for r in gm_rows_data[:50]
    ]
    gm_panel = render_rows_table(
        headers=(
            "Module",
            "File",
            "Score",
            "Status",
            "LOC",
            "Fan-in/out",
            "Complexity total",
        ),
        rows=gm_rows,
        empty_message="Overloaded-module profiling is not available.",
        ctx=ctx,
    )

    sub_tabs: list[tuple[str, str, int, str]] = [
        ("complexity", "Complexity", complexity_high_risk, cx_panel),
        ("coupling", "Coupling (CBO)", coupling_high_risk, cp_panel),
        ("cohesion", "Cohesion (LCOM4)", cohesion_low, ch_panel),
        (
            "overloaded-modules",
            "Overloaded Modules",
            overloaded_module_candidates,
            gm_panel,
        ),
    ]
    coverage_join_panel = render_coverage_join_panel(ctx)
    if coverage_join_panel:
        sub_tabs.append(
            (
                "coverage-join",
                "Coverage Join",
                coverage_review_items,
                coverage_join_panel,
            )
        )

    return insight_block(
        question="Are there quality hotspots in the codebase?",
        answer=answer,
        tone=tone,
    ) + render_split_tabs(group_id="quality", tabs=sub_tabs)
