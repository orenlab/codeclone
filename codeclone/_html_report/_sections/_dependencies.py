# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Dependencies panel renderer (SVG graph + tables)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _render_chain_flow, _short_label, _stat_card, _tab_empty
from ..._html_escape import _escape_attr, _escape_html
from .._components import Tone, insight_block
from .._glossary import glossary_tip
from .._tables import render_rows_table

if TYPE_CHECKING:
    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _select_dep_nodes(
    edges: Sequence[tuple[str, str]],
) -> tuple[list[str], list[tuple[str, str]]]:
    all_nodes = sorted({part for edge in edges for part in edge})
    if len(all_nodes) > 20:
        degree_count: dict[str, int] = dict.fromkeys(all_nodes, 0)
        for source, target in edges:
            degree_count[source] = degree_count.get(source, 0) + 1
            degree_count[target] = degree_count.get(target, 0) + 1
        nodes = sorted(all_nodes, key=lambda node: -degree_count.get(node, 0))[:20]
        nodes.sort()
    else:
        nodes = all_nodes
    node_set = set(nodes)
    filtered = [
        (source, target)
        for source, target in edges
        if source in node_set and target in node_set
    ][:100]
    return nodes, filtered


def _build_degree_maps(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
) -> tuple[dict[str, int], dict[str, int]]:
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    out_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    for source, target in edges:
        in_degree[target] += 1
        out_degree[source] += 1
    return in_degree, out_degree


def _build_layer_groups(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    in_degree: Mapping[str, int],
    out_degree: Mapping[str, int],
) -> dict[int, list[str]]:
    children: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        children[source].append(target)

    layers: dict[str, int] = {}
    roots = sorted(node for node in nodes if in_degree[node] == 0)
    if not roots:
        roots = sorted(nodes, key=lambda node: -out_degree.get(node, 0))[:1]
    queue = list(roots)
    for node in queue:
        layers.setdefault(node, 0)
    while queue:
        node = queue.pop(0)
        for child in children.get(node, []):
            if child in layers:
                continue
            layers[child] = layers[node] + 1
            queue.append(child)

    max_layer = max(layers.values(), default=0)
    for node in nodes:
        if node not in layers:
            layers[node] = max_layer + 1

    layer_groups: dict[int, list[str]] = {}
    for node, layer in layers.items():
        layer_groups.setdefault(layer, []).append(node)
    for layer in layer_groups:
        layer_groups[layer].sort()
    return layer_groups


def _layout_dep_graph(
    layer_groups: Mapping[int, Sequence[str]],
) -> tuple[int, int, int, dict[str, tuple[float, float]]]:
    num_layers = max(layer_groups.keys(), default=0) + 1
    max_per_layer = max((len(members) for members in layer_groups.values()), default=1)
    width = max(600, min(1200, max_per_layer * 70 + 140))
    height = max(260, num_layers * 80 + 80)
    pad_x, pad_y = 60.0, 40.0

    positions: dict[str, tuple[float, float]] = {}
    for layer_index in range(num_layers):
        members = layer_groups.get(layer_index, [])
        count = len(members)
        y = pad_y + layer_index * ((height - 2 * pad_y) / max(1, num_layers - 1))
        for index, node in enumerate(members):
            x = pad_x + (index + 0.5) * ((width - 2 * pad_x) / max(1, count))
            positions[node] = (x, y)
    return width, height, max_per_layer, positions


def _hub_threshold(
    nodes: Sequence[str], in_degree: Mapping[str, int], out_degree: Mapping[str, int]
) -> int:
    degrees = [in_degree.get(node, 0) + out_degree.get(node, 0) for node in nodes]
    if not degrees:
        return 99
    degrees_sorted = sorted(degrees, reverse=True)
    return int(degrees_sorted[max(0, len(degrees_sorted) // 5)])


def _build_node_radii(
    nodes: Sequence[str],
    in_degree: Mapping[str, int],
    out_degree: Mapping[str, int],
    cycle_node_set: set[str],
    hub_threshold: int,
) -> dict[str, float]:
    node_radii: dict[str, float] = {}
    for node in nodes:
        degree = in_degree.get(node, 0) + out_degree.get(node, 0)
        if node in cycle_node_set:
            node_radii[node] = min(8.0, max(5.0, 3.5 + degree * 0.4))
        elif degree >= hub_threshold and degree > 2:
            node_radii[node] = min(10.0, max(6.0, 4.0 + degree * 0.5))
        elif degree <= 1:
            node_radii[node] = 3.0
        else:
            node_radii[node] = min(6.0, max(3.5, 3.0 + degree * 0.3))
    return node_radii


def _build_svg_defs() -> str:
    return (
        "<defs>"
        '<marker id="dep-arrow" viewBox="0 0 10 7" refX="10" refY="3.5" '
        'markerWidth="5" markerHeight="4" orient="auto-start-reverse">'
        '<polygon points="0 0,10 3.5,0 7" fill="var(--border-strong)" fill-opacity="0.5"/></marker>'
        '<marker id="dep-arrow-cycle" viewBox="0 0 10 7" refX="10" refY="3.5" '
        'markerWidth="5" markerHeight="4" orient="auto-start-reverse">'
        '<polygon points="0 0,10 3.5,0 7" fill="var(--danger)" fill-opacity="0.7"/></marker>'
        '<filter id="glow"><feGaussianBlur stdDeviation="2.5" result="g"/>'
        '<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
    )


def _build_cycle_edges(dep_cycles: Sequence[object]) -> set[tuple[str, str]]:
    cycle_edges: set[tuple[str, str]] = set()
    for cycle in dep_cycles:
        parts = [str(part) for part in _as_sequence(cycle)]
        for index in range(len(parts)):
            cycle_edges.add((parts[index], parts[(index + 1) % len(parts)]))
    return cycle_edges


def _render_dep_edges(
    edges: Sequence[tuple[str, str]],
    positions: Mapping[str, tuple[float, float]],
    node_radii: Mapping[str, float],
    cycle_edges: set[tuple[str, str]],
) -> list[str]:
    rendered: list[str] = []
    for source, target in edges:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        source_radius, target_radius = node_radii[source], node_radii[target]
        dx, dy = x2 - x1, y2 - y1
        distance = math.sqrt(dx * dx + dy * dy) or 1.0
        ux, uy = dx / distance, dy / distance
        x1a, y1a = x1 + ux * (source_radius + 2), y1 + uy * (source_radius + 2)
        x2a, y2a = x2 - ux * (target_radius + 4), y2 - uy * (target_radius + 4)
        mx = (x1a + x2a) / 2 - (y2a - y1a) * 0.06
        my = (y1a + y2a) / 2 + (x2a - x1a) * 0.06
        is_cycle = (source, target) in cycle_edges
        stroke = "var(--danger)" if is_cycle else "var(--border-strong)"
        opacity = "0.6" if is_cycle else "0.3"
        marker = "dep-arrow-cycle" if is_cycle else "dep-arrow"
        rendered.append(
            f'<path class="dep-edge" '
            f'data-source="{_escape_attr(source)}" data-target="{_escape_attr(target)}" '
            f'd="M{x1a:.1f},{y1a:.1f} Q{mx:.1f},{my:.1f} {x2a:.1f},{y2a:.1f}" '
            f'fill="none" stroke="{stroke}" stroke-opacity="{opacity}" '
            f'stroke-width="1" marker-end="url(#{marker})"/>'
        )
    return rendered


def _render_dep_nodes_and_labels(
    nodes: Sequence[str],
    *,
    positions: Mapping[str, tuple[float, float]],
    node_radii: Mapping[str, float],
    in_degree: Mapping[str, int],
    out_degree: Mapping[str, int],
    cycle_node_set: set[str],
    hub_threshold: int,
    max_per_layer: int,
) -> tuple[list[str], list[str]]:
    nodes_svg: list[str] = []
    labels_svg: list[str] = []
    rotate_labels = max_per_layer > 6

    for node in nodes:
        x, y = positions[node]
        radius = node_radii[node]
        degree = in_degree.get(node, 0) + out_degree.get(node, 0)
        label = _short_label(node)
        is_cycle = node in cycle_node_set
        is_hub = degree >= hub_threshold and degree > 2

        if is_cycle:
            fill, fill_opacity, extra = (
                "var(--danger)",
                "0.85",
                'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"',
            )
        elif is_hub:
            fill, fill_opacity, extra = (
                "var(--accent-primary)",
                "1",
                'filter="url(#glow)"',
            )
        elif degree <= 1:
            fill, fill_opacity, extra = "var(--text-muted)", "0.4", ""
        else:
            fill, fill_opacity, extra = "var(--accent-primary)", "0.7", ""

        nodes_svg.append(
            f'<circle class="dep-node" data-node="{_escape_attr(node)}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{fill}" fill-opacity="{fill_opacity}" {extra}/>'
        )

        font_size = "10" if is_hub else "9"
        if rotate_labels:
            labels_svg.append(
                f'<text class="dep-label" data-node="{_escape_attr(node)}" '
                f'x="0" y="0" font-size="{font_size}" text-anchor="start" '
                f'transform="translate({x:.1f},{y - radius - 6:.1f}) rotate(-45)">'
                f"<title>{_escape_html(node)}</title>{_escape_html(label)}</text>"
            )
            continue

        labels_svg.append(
            f'<text class="dep-label" data-node="{_escape_attr(node)}" '
            f'x="{x:.1f}" y="{y - radius - 5:.1f}" font-size="{font_size}" text-anchor="middle">'
            f"<title>{_escape_html(node)}</title>{_escape_html(label)}</text>"
        )

    return nodes_svg, labels_svg


def _render_dep_svg(
    edges: Sequence[tuple[str, str]],
    cycle_node_set: set[str],
    dep_cycles: Sequence[object],
) -> str:
    if not edges:
        return _tab_empty("Dependency graph is not available.")

    nodes, filtered_edges = _select_dep_nodes(edges)
    in_degree, out_degree = _build_degree_maps(nodes, filtered_edges)
    layer_groups = _build_layer_groups(nodes, filtered_edges, in_degree, out_degree)
    width, height, max_per_layer, positions = _layout_dep_graph(layer_groups)
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
    )

    label_pad = 50 if max_per_layer > 6 else 0
    vb_y = -label_pad
    vb_h = height + label_pad

    return (
        '<div class="dep-graph-wrap">'
        f'<svg viewBox="0 {vb_y} {width} {vb_h}" class="dep-graph-svg" role="img" '
        'preserveAspectRatio="xMidYMid meet" '
        'aria-label="Module dependency graph">'
        f"{defs}{''.join(edge_svg)}{''.join(node_svg)}{''.join(label_svg)}"
        "</svg></div>"
    )


def render_dependencies_panel(ctx: ReportContext) -> str:
    dep_cycles = _as_sequence(ctx.dependencies_map.get("cycles"))
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
    cycle_count = len(dep_cycles)

    def _mb(*pairs: tuple[str, object]) -> str:
        return "".join(
            f'<span class="kpi-micro">'
            f'<span class="kpi-micro-val">{_escape_html(str(v))}</span>'
            f'<span class="kpi-micro-lbl">{_escape_html(lbl)}</span></span>'
            for lbl, v in pairs
            if v is not None and str(v) != "n/a"
        )

    dep_avg = (
        f"{dep_edge_count / dep_module_count:.1f}" if dep_module_count > 0 else "n/a"
    )

    cards = [
        _stat_card(
            "Modules",
            dep_module_count,
            detail=_mb(("imports", dep_edge_count)),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Edges",
            dep_edge_count,
            detail=_mb(("avg/module", dep_avg)),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max depth",
            dep_max_depth,
            detail=_mb(("target", "< 8")),
            value_tone="warn" if dep_max_depth > 8 else "good",
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Cycles",
            cycle_count,
            detail=(
                _mb(("modules", len(cycle_node_set)))
                if cycle_count > 0
                else _mb(("status", "clean"))
            ),
            value_tone="bad" if cycle_count > 0 else "good",
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
    ]

    # SVG graph
    graph_svg = _render_dep_svg(dep_edges, cycle_node_set, dep_cycles)

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
    dep_longest = _as_sequence(ctx.dependencies_map.get("longest_chains"))
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
        answer = f"Cycles: {cycle_count}; max dependency depth: {dep_max_depth}."
        if cycle_count > 0:
            tone = "risk"
        elif dep_max_depth > 8:
            tone = "warn"
        else:
            tone = "ok"

    return (
        insight_block(
            question="Do module dependencies form cycles?", answer=answer, tone=tone
        )
        + f'<div class="dep-stats">{"".join(cards)}</div>'
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
