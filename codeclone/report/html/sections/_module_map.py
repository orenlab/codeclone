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

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..primitives.escape import _escape_html
from ..widgets.badges import _micro_badges, _short_label, _stat_card, _tab_empty
from ..widgets.components import Tone, insight_block
from ..widgets.dep_graph_layout import (
    _build_degree_maps,
    _build_layer_groups,
    _build_node_radii,
    _build_svg_defs,
    _hub_threshold,
    _layout_dep_graph,
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
    '<svg width="12" height="12"><circle cx="6" cy="6" r="5" '
    'fill="var(--accent-primary)"/></svg> Hub</span>'
    '<span class="dep-legend-item">'
    '<svg width="14" height="14"><circle cx="7" cy="7" r="4" '
    'fill="var(--accent-primary)" fill-opacity="0.7"/>'
    '<circle cx="7" cy="7" r="6" class="mm-candidate-ring"/></svg> '
    "Overload candidate</span>"
    '<span class="dep-legend-item">'
    '<svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="none" '
    'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"/></svg> '
    "In cycle</span>"
    '<span class="dep-legend-item">'
    '<svg width="12" height="12"><circle cx="6" cy="6" r="3" '
    'fill="var(--text-muted)" fill-opacity="0.4"/></svg> Leaf</span></div>'
)


def _mm_edge_stroke_width(weight: int) -> int:
    if weight <= 1:
        return 1
    return 1 + min(3, math.floor(math.log2(weight)))


def _render_mm_edges(
    edges: Sequence[tuple[str, str]],
    positions: Mapping[str, tuple[float, float]],
    node_radii: Mapping[str, float],
    weights: Mapping[tuple[str, str], int],
) -> list[str]:
    rendered: list[str] = []
    for source, target in edges:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        ux, uy = _unit_vector(x1, y1, x2, y2)
        sx, sy = x1 + ux * (node_radii[source] + 2), y1 + uy * (node_radii[source] + 2)
        tx, ty = x2 - ux * (node_radii[target] + 4), y2 - uy * (node_radii[target] + 4)
        stroke_width = _mm_edge_stroke_width(weights.get((source, target), 1))
        rendered.append(
            f'<line class="dep-edge" '
            f'data-source="{_escape_html(source)}" '
            f'data-target="{_escape_html(target)}" '
            f'x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
            f'stroke="var(--border-strong)" stroke-opacity="0.35" '
            f'stroke-width="{stroke_width}" marker-end="url(#dep-arrow)"/>'
        )
    return rendered


def _unit_vector(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    dx, dy = x2 - x1, y2 - y1
    distance = math.hypot(dx, dy) or 1.0
    return dx / distance, dy / distance


def _mm_node_fill(
    *, in_cycle: bool, is_hub: bool, total_degree: int, is_tests: bool
) -> tuple[str, str, str]:
    if in_cycle:
        return (
            "var(--danger)",
            "0.85",
            'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"',
        )
    if is_hub:
        return "var(--accent-primary)", "1", 'filter="url(#glow)"'
    if total_degree <= 1:
        return "var(--text-muted)", "0.4", ""
    extra = (
        'stroke="var(--border-strong)" stroke-width="1" stroke-dasharray="2,2"'
        if is_tests
        else ""
    )
    return "var(--accent-primary)", "0.7", extra


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


def _render_mm_nodes(
    nodes: Sequence[Mapping[str, object]],
    *,
    positions: Mapping[str, tuple[float, float]],
    node_radii: Mapping[str, float],
    hub_threshold: int,
) -> tuple[list[str], list[str]]:
    nodes_svg: list[str] = []
    labels_svg: list[str] = []
    for node in nodes:
        node_id = str(node.get("id"))
        x, y = positions[node_id]
        radius = node_radii[node_id]
        total_degree = _as_int(node.get("total_degree"))
        overloaded = _as_mapping(node.get("overloaded"))
        is_hub = total_degree >= hub_threshold and total_degree > 2
        is_tests = [str(k) for k in _as_sequence(node.get("source_kinds"))] == ["tests"]
        fill, opacity, extra = _mm_node_fill(
            in_cycle=bool(node.get("in_cycle")),
            is_hub=is_hub,
            total_degree=total_degree,
            is_tests=is_tests,
        )
        nodes_svg.append(
            f'<circle class="dep-node" data-node="{_escape_html(node_id)}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{fill}" fill-opacity="{opacity}" {extra}/>'
        )
        if str(overloaded.get("candidate_status")) == _CANDIDATE:
            nodes_svg.append(
                f'<circle class="mm-candidate-ring" cx="{x:.1f}" cy="{y:.1f}" '
                f'r="{radius + 2.5:.1f}"/>'
            )
        labels_svg.append(
            f'<text class="dep-label" data-node="{_escape_html(node_id)}" '
            f'x="0" y="0" font-size="9" text-anchor="start" '
            f'transform="translate({x + radius + 4:.1f},{y - radius - 2:.1f}) '
            f'rotate(-45)"><title>'
            f"{_escape_html(_mm_node_title(node, overloaded))}</title>"
            f"{_escape_html(_short_label(node_id))}</text>"
        )
    return nodes_svg, labels_svg


def _render_module_map_svg(graph: Mapping[str, object]) -> str:
    nodes = [_as_mapping(node) for node in _as_sequence(graph.get("nodes"))]
    if not nodes:
        return _tab_empty(_EMPTY_GRAPH_MESSAGE)
    node_ids = [str(node.get("id")) for node in nodes]
    edge_rows = [_as_mapping(edge) for edge in _as_sequence(graph.get("edges"))]
    edges = [(str(e.get("source")), str(e.get("target"))) for e in edge_rows]
    weights = {
        (str(e.get("source")), str(e.get("target"))): _as_int(e.get("weight"))
        for e in edge_rows
    }
    cycle_node_set = {
        str(node.get("id")) for node in nodes if bool(node.get("in_cycle"))
    }
    total_in = {str(n.get("id")): _as_int(n.get("total_degree")) for n in nodes}
    total_out = dict.fromkeys(node_ids, 0)

    layout_in, layout_out = _build_degree_maps(node_ids, edges)
    layer_groups = _build_layer_groups(node_ids, edges, layout_in, layout_out)
    width, height, _max_per_layer, positions = _layout_dep_graph(
        layer_groups, in_degree=layout_in, out_degree=layout_out
    )
    hub_threshold = _hub_threshold(node_ids, total_in, total_out)
    node_radii = _build_node_radii(
        node_ids, total_in, total_out, cycle_node_set, hub_threshold
    )

    defs = _build_svg_defs()
    edge_svg = _render_mm_edges(edges, positions, node_radii, weights)
    node_svg, label_svg = _render_mm_nodes(
        nodes, positions=positions, node_radii=node_radii, hub_threshold=hub_threshold
    )

    pad = 60
    return (
        '<div class="dep-graph-wrap">'
        f'<svg viewBox="{-pad} {-pad} {width + pad * 2} {height + pad}" '
        'class="dep-graph-svg" role="img" preserveAspectRatio="xMidYMid meet" '
        'aria-label="Module map graph">'
        f"{defs}{''.join(edge_svg)}{''.join(node_svg)}{''.join(label_svg)}"
        "</svg></div>"
    )


def _mm_stat_cards(
    summary: Mapping[str, object], active_graph: Mapping[str, object]
) -> str:
    truncation = _as_mapping(active_graph.get("truncation"))
    cards = [
        _stat_card(
            "Nodes shown",
            _as_int(truncation.get("node_shown_count")),
            detail=_micro_badges(
                ("of", _as_int(truncation.get("node_universe_count")))
            ),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Edges shown",
            _as_int(truncation.get("edge_shown_count")),
            detail=_micro_badges(
                ("of", _as_int(truncation.get("edge_universe_count")))
            ),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Unwind candidates",
            _as_int(summary.get("unwind_candidate_count")),
            detail=_micro_badges(
                ("modules", _as_int(summary.get("module_count"))),
                ("packages", _as_int(summary.get("package_count_depth2"))),
            ),
            css_class="meta-item",
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
