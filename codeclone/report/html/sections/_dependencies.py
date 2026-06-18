# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Dependencies panel renderer (SVG graph + tables)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from codeclone.metrics.dependencies import select_dependency_graph_nodes
from codeclone.utils import coerce as _coerce

from ..primitives.escape import _escape_html
from ..widgets.badges import (
    _micro_badges,
    _render_chain_flow,
    _short_label,
    _stat_card,
    _tab_empty,
)
from ..widgets.components import Tone, insight_block
from ..widgets.dep_graph_layout import (
    _build_cycle_edges,
    _build_degree_maps,
    _build_layer_groups,
    _build_node_radii,
    _build_svg_defs,
    _hub_threshold,
    _layout_dep_graph,
    _render_dep_edges,
    _render_dep_nodes_and_labels,
)
from ..widgets.glossary import glossary_tip
from ..widgets.tables import render_rows_table

if TYPE_CHECKING:
    from .._context import ReportContext

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _select_dep_nodes(
    edges: Sequence[tuple[str, str]],
    *,
    dep_cycles: Sequence[object],
    longest_chains: Sequence[object],
) -> tuple[list[str], list[tuple[str, str]]]:
    # Shared deterministic sampler (metrics.dependencies). Dependencies tab keeps
    # its historical caps (20 nodes / 100 edges) and module-level identity zoom.
    nodes, filtered, _truncation = select_dependency_graph_nodes(
        edges,
        dep_cycles=dep_cycles,
        longest_chains=longest_chains,
        max_nodes=20,
        max_edges=100,
    )
    return nodes, filtered


def _render_dep_svg(
    edges: Sequence[tuple[str, str]],
    cycle_node_set: set[str],
    dep_cycles: Sequence[object],
    longest_chains: Sequence[object],
) -> str:
    if not edges:
        return _tab_empty("Dependency graph is not available.")

    nodes, filtered_edges = _select_dep_nodes(
        edges,
        dep_cycles=dep_cycles,
        longest_chains=longest_chains,
    )
    in_degree, out_degree = _build_degree_maps(nodes, filtered_edges)
    layer_groups = _build_layer_groups(nodes, filtered_edges, in_degree, out_degree)
    width, height, max_per_layer, positions = _layout_dep_graph(
        layer_groups,
        in_degree=in_degree,
        out_degree=out_degree,
    )
    prefer_horizontal = width > height
    hub_threshold = _hub_threshold(nodes, in_degree, out_degree)
    node_radii = _build_node_radii(
        nodes,
        in_degree,
        out_degree,
        cycle_node_set,
        hub_threshold,
    )
    cycle_edges = _build_cycle_edges(dep_cycles)
    defs = _build_svg_defs()
    edge_svg = _render_dep_edges(filtered_edges, positions, node_radii, cycle_edges)
    node_svg, label_svg = _render_dep_nodes_and_labels(
        nodes,
        positions=positions,
        node_radii=node_radii,
        in_degree=in_degree,
        out_degree=out_degree,
        cycle_node_set=cycle_node_set,
        hub_threshold=hub_threshold,
        max_per_layer=max_per_layer,
        prefer_horizontal=prefer_horizontal,
    )

    label_pad = 44 if prefer_horizontal else (50 if max_per_layer > 6 else 0)
    label_pad_x = 52 if prefer_horizontal else (28 if max_per_layer > 6 else 0)
    vb_x = -label_pad_x
    vb_y = -label_pad
    vb_w = width + label_pad_x * 2
    vb_h = height + label_pad

    return (
        '<div class="dep-graph-wrap">'
        f'<svg viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" class="dep-graph-svg" role="img" '
        'preserveAspectRatio="xMidYMid meet" '
        'aria-label="Module dependency graph">'
        f"{defs}{''.join(edge_svg)}{''.join(node_svg)}{''.join(label_svg)}"
        "</svg></div>"
    )


def render_dependencies_panel(ctx: ReportContext) -> str:
    dep_cycles = _as_sequence(ctx.dependencies_map.get("cycles"))
    dep_longest = _as_sequence(ctx.dependencies_map.get("longest_chains"))
    dep_edge_data = _as_sequence(ctx.dependencies_map.get("edge_list"))
    dep_edges = [
        (str(_as_mapping(r).get("source", "")), str(_as_mapping(r).get("target", "")))
        for r in dep_edge_data
        if _as_mapping(r).get("source") and _as_mapping(r).get("target")
    ]

    cycle_node_set: set[str] = set()
    for cyc in dep_cycles:
        for p in _as_sequence(cyc):
            cycle_node_set.add(str(p))

    dep_module_count = _as_int(ctx.dependencies_map.get("modules"))
    dep_edge_count = _as_int(ctx.dependencies_map.get("edges"))
    dep_max_depth = _as_int(ctx.dependencies_map.get("max_depth"))
    dep_avg_depth = _as_float(ctx.dependencies_map.get("avg_depth"))
    dep_p95_depth = _as_int(ctx.dependencies_map.get("p95_depth"))
    cycle_count = len(dep_cycles)
    dependency_health = _as_int(
        _as_mapping(ctx.health_map.get("dimensions")).get("dependencies"),
    )

    dep_avg = (
        f"{dep_edge_count / dep_module_count:.1f}" if dep_module_count > 0 else "n/a"
    )
    dep_avg_depth_label = f"{dep_avg_depth:.1f}" if dep_module_count > 0 else "n/a"

    dependency_tone: Tone
    if cycle_count > 0:
        dependency_tone = "risk"
    elif dependency_health < 100:
        dependency_tone = "warn"
    else:
        dependency_tone = "ok"

    cards = [
        _stat_card(
            "Modules",
            dep_module_count,
            detail=_micro_badges(("imports", dep_edge_count)),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Edges",
            dep_edge_count,
            detail=_micro_badges(("avg/module", dep_avg)),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max depth",
            dep_max_depth,
            detail=_micro_badges(
                ("avg", dep_avg_depth_label),
                ("p95", dep_p95_depth),
            ),
            value_tone="bad"
            if cycle_count > 0
            else ("warn" if dependency_health < 100 else "good"),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Cycles",
            cycle_count,
            detail=(
                _micro_badges(("modules", len(cycle_node_set)))
                if cycle_count > 0
                else _micro_badges(("status", "clean"))
            ),
            value_tone="bad" if cycle_count > 0 else "good",
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
    ]

    # SVG graph
    graph_svg = _render_dep_svg(
        dep_edges,
        cycle_node_set,
        dep_cycles,
        dep_longest,
    )

    # Hub bar
    deg_map = dict.fromkeys(sorted({p for e in dep_edges for p in e}), 0)
    for s, t in dep_edges:
        deg_map[s] += 1
        deg_map[t] += 1
    top_nodes = sorted(deg_map, key=lambda n: (-deg_map[n], n))[:5]
    hub_pills = "".join(
        f'<span class="dep-hub-pill">'
        f'<span class="dep-hub-name">{_escape_html(_short_label(n))}</span>'
        f'<span class="dep-hub-deg">{deg_map[n]}</span></span>'
        for n in top_nodes
    )
    hub_bar = (
        f'<div class="dep-hub-bar"><span class="dep-hub-label">Top connected</span>{hub_pills}</div>'
        if top_nodes
        else ""
    )

    # Legend
    legend = (
        '<div class="dep-legend">'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="var(--accent-primary)"/></svg> Hub</span>'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="3" fill="var(--text-muted)" fill-opacity="0.4"/></svg> Leaf</span>'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="none" '
        'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"/></svg> Cycle</span></div>'
    )

    # Tables
    dep_cycle_rows = [
        (_render_chain_flow([str(p) for p in _as_sequence(c)], arrows=True),)
        for c in dep_cycles
    ]
    dep_chain_rows = [
        (
            _render_chain_flow([str(p) for p in _as_sequence(ch)], arrows=True),
            str(len(_as_sequence(ch))),
        )
        for ch in dep_longest
    ]

    # Insight
    answer: str
    tone: Tone
    if not ctx.metrics_available:
        answer, tone = "Metrics are skipped for this run.", "info"
    else:
        answer = (
            f"Cycles: {cycle_count}; avg depth: {dep_avg_depth_label}; "
            f"p95 depth: {dep_p95_depth}; max dependency depth: {dep_max_depth}."
        )
        tone = dependency_tone

    return (
        insight_block(
            question="Do module dependencies form cycles?", answer=answer, tone=tone
        )
        + f'<div class="stat-cards">{"".join(cards)}</div>'
        + hub_bar
        + graph_svg
        + legend
        + '<h3 class="subsection-title">Longest chains</h3>'
        + render_rows_table(
            headers=("Longest chain", "Length"),
            rows=dep_chain_rows,
            empty_message="No dependency chains detected.",
            raw_html_headers=("Longest chain",),
            ctx=ctx,
        )
        + '<h3 class="subsection-title">Detected cycles</h3>'
        + render_rows_table(
            headers=("Cycle",),
            rows=dep_cycle_rows,
            empty_message="No dependency cycles detected.",
            raw_html_headers=("Cycle",),
            ctx=ctx,
        )
    )
