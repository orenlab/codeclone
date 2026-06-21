# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Module map panel renderer.

Render-only: draws the precomputed ``derived.module_map`` graph (sampled
packages/modules), unwind-candidate triage, and a top-overloaded slice. No
projection math lives here — the graph, truncation, and unwind rows are
computed once in ``report.document.derived``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..widgets.badges import _micro_badges, _stat_card, _tab_empty
from ..widgets.components import Tone, insight_block
from ..widgets.dep_graph_layout import (
    BlockNodeStyle,
    _hub_threshold,
    block_node_style_for,
    render_block_diagram,
)
from ..widgets.glossary import glossary_tip
from ..widgets.tables import render_rows_table

if TYPE_CHECKING:
    from .._context import ReportContext

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

_CANDIDATE = "candidate"
_OVERLOADED_TABLE_CAP = 50
_OVERLOADED_HEADING = "Overloaded Modules"
_EMPTY_GRAPH_MESSAGE = "Dependency graph is not available."
_OVERLOADED_EMPTY_MESSAGE = "Overloaded-module profiling is not available."
_METRICS_SKIPPED = "Metrics are skipped for this run."

# Mandatory honesty copy (spec §11): report-only, sampled SVG, full tables.
_MODULE_MAP_INSIGHT = (
    "Report-only import-graph signals for refactor triage. Not CI gates. The SVG "
    "may show a deterministic sample of packages/modules on large repos; unwind "
    "and overload tables list module-level facts for the full codebase. Verify in "
    "source before editing."
)

_MM_LEGEND = (
    '<div class="dep-legend">'
    '<span class="dep-legend-item">'
    '<svg width="16" height="12"><rect x="0.5" y="1" width="15" height="10" rx="3" '
    'fill="var(--accent-primary)"/></svg> Hub</span>'
    '<span class="dep-legend-item">'
    '<svg width="20" height="14"><rect x="2.5" y="2" width="15" height="10" rx="3" '
    'fill="var(--bg-overlay)" stroke="var(--border-strong)"/>'
    '<rect x="0.5" y="0.5" width="19" height="13" rx="4" fill="none" '
    'stroke="var(--warning)" stroke-width="1.5"/></svg> Overload candidate</span>'
    '<span class="dep-legend-item">'
    '<svg width="16" height="12"><rect x="0.5" y="1" width="15" height="10" rx="3" '
    'fill="var(--bg-surface)" stroke="var(--danger)" stroke-dasharray="4,3"/></svg> '
    "In cycle</span>"
    '<span class="dep-legend-item">'
    '<svg width="16" height="12"><rect x="0.5" y="1" width="15" height="10" rx="3" '
    'fill="var(--bg-surface)" stroke="var(--border)"/></svg> Leaf</span></div>'
)


def _mm_node_title(node: Mapping[str, object], overloaded: Mapping[str, object]) -> str:
    reasons = ", ".join(
        str(reason) for reason in _as_sequence(overloaded.get("candidate_reasons"))
    )
    title = (
        f"{node.get('id')} · in {_as_int(node.get('fan_in'))} · "
        f"out {_as_int(node.get('fan_out'))} · "
        f"score {_as_float(overloaded.get('score')):.2f}"
    )
    if reasons:
        title = f"{title} · {reasons}"
    return title


def _mm_node_style(node: Mapping[str, object], *, hub_threshold: int) -> BlockNodeStyle:
    total_degree = _as_int(node.get("total_degree"))
    overloaded = _as_mapping(node.get("overloaded"))
    is_candidate = str(overloaded.get("candidate_status")) == _CANDIDATE
    is_tests = [str(k) for k in _as_sequence(node.get("source_kinds"))] == ["tests"]
    return block_node_style_for(
        in_cycle=bool(node.get("in_cycle")),
        is_hub=total_degree >= hub_threshold and total_degree > 2,
        is_leaf=total_degree <= 1,
        ring="var(--warning)" if is_candidate else "",
        dashed=is_tests,
        title=_mm_node_title(node, overloaded),
    )


def _render_module_map_svg(graph: Mapping[str, object]) -> str:
    nodes = [_as_mapping(node) for node in _as_sequence(graph.get("nodes"))]
    if not nodes:
        return _tab_empty(_EMPTY_GRAPH_MESSAGE)
    node_ids = [str(node.get("id")) for node in nodes]
    by_id = {str(node.get("id")): node for node in nodes}
    edge_rows = [_as_mapping(edge) for edge in _as_sequence(graph.get("edges"))]
    edges = [(str(e.get("source")), str(e.get("target"))) for e in edge_rows]
    weights = {
        (str(e.get("source")), str(e.get("target"))): _as_int(e.get("weight"))
        for e in edge_rows
    }
    total_degree = {nid: _as_int(by_id[nid].get("total_degree")) for nid in node_ids}
    hub_threshold = _hub_threshold(node_ids, total_degree, dict.fromkeys(node_ids, 0))

    def _style(node_id: str) -> BlockNodeStyle:
        return _mm_node_style(by_id[node_id], hub_threshold=hub_threshold)

    return render_block_diagram(
        node_ids,
        edges,
        style_fn=_style,
        aria_label="Module map graph",
        edge_weight_fn=lambda edge: weights.get(edge, 1),
    )


def _mm_stat_cards(
    summary: Mapping[str, object], active_graph: Mapping[str, object]
) -> str:
    truncation = _as_mapping(active_graph.get("truncation"))
    node_total = _as_int(truncation.get("node_universe_count"))
    edge_total = _as_int(truncation.get("edge_universe_count"))
    graph_subtext = (
        "deterministic sample" if bool(truncation.get("truncated")) else "full graph"
    )
    cards = [
        _stat_card(
            "Nodes shown",
            _as_int(truncation.get("node_shown_count")),
            secondary=f"/ {node_total}",
            subtext=graph_subtext,
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Edges shown",
            _as_int(truncation.get("edge_shown_count")),
            secondary=f"/ {edge_total}",
            subtext=graph_subtext,
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Unwind candidates",
            _as_int(summary.get("unwind_candidate_count")),
            subtext=(
                f"of {_as_int(summary.get('module_count'))} modules · "
                f"{_as_int(summary.get('package_count_depth2'))} packages"
            ),
            value_tone="accent",
            css_class="meta-item meta-item--accent",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return "".join(cards)


def _mm_truncation_notice(active_graph: Mapping[str, object]) -> str:
    truncation = _as_mapping(active_graph.get("truncation"))
    if not bool(truncation.get("truncated")):
        return ""
    return (
        '<div class="mm-truncation-notice">'
        f"Showing {_as_int(truncation.get('node_shown_count'))} of "
        f"{_as_int(truncation.get('node_universe_count'))} nodes and "
        f"{_as_int(truncation.get('edge_shown_count'))} of "
        f"{_as_int(truncation.get('edge_universe_count'))} edges — a deterministic "
        "sample seeded by cycles, then chains, then degree. Tables below are full."
        "</div>"
    )


def _mm_zoom_toggle(
    default_zoom: str,
    graph_packages: Mapping[str, object],
    graph_modules: Mapping[str, object],
) -> str:
    packages_svg = _render_module_map_svg(graph_packages)
    modules_svg = _render_module_map_svg(graph_modules)
    package_count = len(_as_sequence(graph_packages.get("nodes")))
    module_count = len(_as_sequence(graph_modules.get("nodes")))
    packages_active = "active" if default_zoom == "packages" else ""
    modules_active = "" if default_zoom == "packages" else "active"
    return (
        '<nav class="clone-nav" role="tablist" data-subtab-group="module-map-zoom">'
        f'<button class="clone-nav-btn {packages_active}" '
        'data-clone-tab="packages" data-subtab-group="module-map-zoom" '
        f'type="button">Packages <span class="tab-count">{package_count}</span>'
        "</button>"
        f'<button class="clone-nav-btn {modules_active}" '
        'data-clone-tab="modules" data-subtab-group="module-map-zoom" '
        f'type="button">Modules <span class="tab-count">{module_count}</span>'
        "</button></nav>"
        f'<div class="clone-panel {packages_active}" data-clone-panel="packages" '
        f'data-subtab-group="module-map-zoom">{packages_svg}</div>'
        f'<div class="clone-panel {modules_active}" data-clone-panel="modules" '
        f'data-subtab-group="module-map-zoom">{modules_svg}</div>'
    )


def _mm_unwind_table(unwind_candidates: Sequence[object], ctx: ReportContext) -> str:
    rows = [
        (
            str(_as_mapping(row).get("module")),
            str(_as_int(_as_mapping(row).get("fan_in"))),
            str(_as_int(_as_mapping(row).get("fan_out"))),
            f"{_as_float(_as_mapping(row).get('score')):.2f}",
            str(_as_mapping(row).get("candidate_status")),
            ", ".join(str(s) for s in _as_sequence(_as_mapping(row).get("signals"))),
        )
        for row in unwind_candidates
    ]
    return render_rows_table(
        headers=("Module", "Fan-in", "Fan-out", "Score", "Status", "Signals"),
        rows=rows,
        empty_message="No unwind candidates detected.",
        column_types={
            "Fan-in": "meter",
            "Fan-out": "meter",
            "Score": "score",
            "Status": "status",
            "Signals": "chips",
        },
        ctx=ctx,
    )


def _overloaded_cards(
    summary: Mapping[str, object],
    rows_data: Sequence[object],
) -> str:
    candidates = _as_int(summary.get("candidates"))
    total_modules = _as_int(summary.get("total"))
    ranked_only = sum(
        1
        for r in rows_data
        if str(_as_mapping(r).get("candidate_status", "")).strip().lower()
        == "ranked_only"
    )
    population_status = str(summary.get("population_status", "")).strip().lower()
    max_score = _as_float(summary.get("top_score"))
    if max_score <= 0.0:
        row_scores = [_as_float(_as_mapping(r).get("score")) for r in rows_data]
        max_score = max(row_scores) if row_scores else 0.0
    cutoff = _as_float(summary.get("candidate_score_cutoff"))
    locs = [
        _as_int(_as_mapping(r).get("loc"))
        for r in rows_data
        if _as_int(_as_mapping(r).get("loc")) > 0
    ]
    avg_loc = int(sum(locs) / len(locs)) if locs else 0
    cards = [
        _stat_card(
            "Overloaded",
            candidates,
            detail=_micro_badges(("total analyzed", total_modules)),
            value_tone="bad" if candidates > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Ranked only",
            ranked_only,
            detail=_micro_badges(("population", population_status))
            if population_status
            else "",
            value_tone=(
                "warn"
                if population_status == "limited"
                else ("muted" if ranked_only else "good")
            ),
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max score",
            f"{max_score:.2f}",
            detail=_micro_badges(("cutoff", f"{cutoff:.2f}")) if cutoff > 0.0 else "",
            value_tone="warn" if max_score > 0 else "muted",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Avg LOC",
            avg_loc,
            detail=_micro_badges(("modules", len(locs))),
            value_tone="muted",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return f'<div class="stat-cards">{"".join(cards)}</div>'


def _render_overloaded_modules_section(ctx: ReportContext) -> str:
    """Render the full overloaded-modules profile (cards + table).

    Driven by ``metrics.families.overloaded_modules`` directly, so it renders
    independently of dependency-graph availability — overloaded responsibility
    is module-level and belongs in the Module map regardless of graph sampling.
    """
    overloaded = _as_mapping(ctx.overloaded_modules_map)
    if not overloaded:
        return ""
    summary = _as_mapping(overloaded.get("summary"))
    rows_data = _as_sequence(overloaded.get("items"))
    rows = [
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
        for r in rows_data[:_OVERLOADED_TABLE_CAP]
    ]
    return (
        f'<h3 class="subsection-title">{_OVERLOADED_HEADING}</h3>'
        + _overloaded_cards(summary, rows_data)
        + render_rows_table(
            headers=(
                "Module",
                "File",
                "Score",
                "Status",
                "LOC",
                "Fan-in/out",
                "Complexity total",
            ),
            rows=rows,
            empty_message=_OVERLOADED_EMPTY_MESSAGE,
            column_types={
                "Score": "score",
                "Status": "status",
                "LOC": "meter",
                "Complexity total": "meter",
            },
            ctx=ctx,
        )
    )


def _render_graph_block(ctx: ReportContext, module_map: Mapping[str, object]) -> str:
    summary = _as_mapping(module_map.get("summary"))
    if not module_map or not bool(summary.get("available")):
        return _tab_empty(_EMPTY_GRAPH_MESSAGE)

    default_zoom = str(module_map.get("default_zoom") or "packages")
    graph_packages = _as_mapping(module_map.get("graph_packages"))
    graph_modules = _as_mapping(module_map.get("graph_modules"))
    active_graph = graph_packages if default_zoom == "packages" else graph_modules

    return (
        _mm_truncation_notice(active_graph)
        + f'<div class="stat-cards">{_mm_stat_cards(summary, active_graph)}</div>'
        + _mm_zoom_toggle(default_zoom, graph_packages, graph_modules)
        + _MM_LEGEND
        + '<h3 class="subsection-title">Unwind candidates</h3>'
        + _mm_unwind_table(_as_sequence(module_map.get("unwind_candidates")), ctx)
    )


def render_module_map_panel(ctx: ReportContext) -> str:
    module_map = _as_mapping(ctx.derived_map.get("module_map"))

    answer = _MODULE_MAP_INSIGHT if ctx.metrics_available else _METRICS_SKIPPED
    tone: Tone = "info"
    insight = insight_block(
        question="Where should refactoring unwind dependencies?",
        answer=answer,
        tone=tone,
    )

    # The import graph + unwind triage need the derived projection; the
    # overloaded-modules profile is a module-level metrics view that renders
    # independently (it moved here from the Quality tab — single home for
    # module responsibility).
    return (
        insight
        + _render_graph_block(ctx, module_map)
        + _render_overloaded_modules_section(ctx)
    )
