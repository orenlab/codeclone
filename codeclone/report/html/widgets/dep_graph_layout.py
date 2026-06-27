# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared block-diagram SVG layout for module/dependency graphs.

Renders a layered flowchart: rectangular nodes with the label inside, stacked
top→bottom by topological depth, joined by lane-aware curved connectors whose
arrows point in import direction (``source`` → ``target``). Both the
Dependencies tab and the Module map tab draw through
:func:`render_block_diagram`, passing a per-node :class:`BlockNodeStyle`
callback, so the geometry stays identical and each tab only owns its own node
accents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha1
from typing import TYPE_CHECKING

from codeclone.utils.coerce import as_sequence

from ..primitives.escape import _escape_html
from .badges import _short_label

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from collections.abc import Set as AbstractSet

_BOX_H = 32
_BOX_W_MIN = 76
_BOX_W_MAX = 184
_BOX_CHAR_W = 8
_BOX_PAD_X = 30
_LABEL_PAD_X = 28
_ROW_GAP = 92
_COL_GAP = 30
_BLOCK_PAD = 34
_LABEL_MAX = 20
_MAX_ROW_WIDTH = 980
_WRAPPED_ROW_GAP = 54
# Fan endpoints spread across this fraction of a box edge so converging arrows
# enter/leave at distinct points instead of clumping at the centre.
_FAN_SPREAD_FRAC = 0.70
_FAN_SPREAD_STEP = 17.0
_LANE_STEP = 10.0
_COMPACT_NODE_LIMIT = 8
_WIDE_NODE_LIMIT = 18
_COMPACT_RENDER_MAX = 820
_COMFORTABLE_RENDER_MAX = 1320
_WIDE_RENDER_MAX = 1180


@dataclass(frozen=True, slots=True)
class BlockNodeStyle:
    """Per-node visual accent for a block-diagram node.

    ``ring`` draws an outer halo (overload candidate); ``dashed`` dashes the box
    border (test-only modules); empty strings/False mean "no accent".
    """

    fill: str
    text_fill: str
    stroke: str = "var(--border)"
    ring: str = ""
    dashed: bool = False
    title: str = ""


def block_node_style_for(
    *,
    in_cycle: bool,
    is_hub: bool,
    is_leaf: bool,
    ring: str = "",
    dashed: bool = False,
    title: str = "",
) -> BlockNodeStyle:
    """Shared node palette for both graph tabs (single visual vocabulary).

    Precedence: cycle (danger, dashed) → hub (indigo fill) → leaf (muted) →
    ordinary. ``ring`` (overload candidate) and ``dashed`` (test-only modules)
    are independent accents the caller opts into.
    """
    if in_cycle:
        return BlockNodeStyle(
            fill="var(--bg-surface)",
            text_fill="var(--danger)",
            stroke="var(--danger)",
            ring=ring,
            dashed=True,
            title=title,
        )
    if is_hub:
        return BlockNodeStyle(
            fill="var(--accent-primary)",
            text_fill="#fff",
            stroke="var(--accent-primary)",
            ring=ring,
            title=title,
        )
    if is_leaf:
        return BlockNodeStyle(
            fill="var(--bg-surface)",
            text_fill="var(--text-muted)",
            stroke="var(--border)",
            ring=ring,
            title=title,
        )
    return BlockNodeStyle(
        fill="var(--bg-overlay)",
        text_fill="var(--text-secondary)",
        stroke="var(--border-strong)",
        ring=ring,
        dashed=dashed,
        title=title,
    )


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


def _hub_threshold(
    nodes: Sequence[str], in_degree: Mapping[str, int], out_degree: Mapping[str, int]
) -> int:
    degrees = [in_degree.get(node, 0) + out_degree.get(node, 0) for node in nodes]
    if not degrees:
        return 99
    degrees_sorted = sorted(degrees, reverse=True)
    return int(degrees_sorted[max(0, len(degrees_sorted) // 5)])


def _build_cycle_edges(dep_cycles: Sequence[object]) -> set[tuple[str, str]]:
    cycle_edges: set[tuple[str, str]] = set()
    for cycle in dep_cycles:
        parts = [str(part) for part in as_sequence(cycle)]
        for index in range(len(parts)):
            cycle_edges.add((parts[index], parts[(index + 1) % len(parts)]))
    return cycle_edges


def _box_width(label: str) -> int:
    return min(_BOX_W_MAX, max(_BOX_W_MIN, len(label) * _BOX_CHAR_W + _BOX_PAD_X))


def _label_fit_attrs(label: str, width: int) -> str:
    """Clamp long SVG text to the node's inner width across browser fonts."""
    max_text_width = max(18.0, width - _LABEL_PAD_X)
    if len(label) * _BOX_CHAR_W <= max_text_width:
        return ""
    return f' textLength="{max_text_width:.1f}" lengthAdjust="spacingAndGlyphs"'


def _edge_stroke_width(weight: int) -> int:
    if weight <= 1:
        return 1
    return 1 + min(2, math.floor(math.log2(weight)))


def _layout_block_diagram(
    layer_groups: Mapping[int, Sequence[str]],
    box_widths: Mapping[str, int],
    degree: Mapping[str, int] | None = None,
) -> tuple[int, int, dict[str, tuple[float, float]]]:
    """Place each node box centre-aligned per topological layer (top→bottom)."""
    degree = degree or {}
    num_layers = max(layer_groups.keys(), default=0) + 1

    def _ordered_members(members: Sequence[str]) -> list[str]:
        if len(members) < 3:
            return list(members)
        ranked = sorted(members, key=lambda node: (-degree.get(node, 0), node))
        center = (len(ranked) - 1) / 2
        slots = sorted(range(len(ranked)), key=lambda idx: (abs(idx - center), idx))
        ordered = [""] * len(ranked)
        for node, slot in zip(ranked, slots, strict=False):
            ordered[slot] = node
        return ordered

    def _row_width(members: Sequence[str]) -> int:
        if not members:
            return 0
        return sum(box_widths[m] for m in members) + _COL_GAP * (len(members) - 1)

    def _wrapped_rows(members: Sequence[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        current: list[str] = []
        current_width = 0
        for member in members:
            member_width = box_widths[member]
            next_width = (
                member_width if not current else current_width + _COL_GAP + member_width
            )
            if current and next_width > _MAX_ROW_WIDTH:
                rows.append(current)
                current = [member]
                current_width = member_width
                continue
            current.append(member)
            current_width = next_width
        if current:
            rows.append(current)
        return rows or [[]]

    visual_rows: list[list[str]] = []
    row_logical_layers: list[int] = []
    for layer in range(num_layers):
        rows = _wrapped_rows(_ordered_members(layer_groups.get(layer, [])))
        visual_rows.extend(rows)
        row_logical_layers.extend([layer] * len(rows))
    row_widths = [_row_width(row) for row in visual_rows]
    canvas_width = max(row_widths, default=0)

    positions: dict[str, tuple[float, float]] = {}
    current_y = _BOX_H / 2
    previous_layer: int | None = None
    for visual_index, members in enumerate(visual_rows):
        layer = row_logical_layers[visual_index]
        if visual_index > 0:
            current_y += _WRAPPED_ROW_GAP if previous_layer == layer else _ROW_GAP
        cursor = (canvas_width - row_widths[visual_index]) / 2
        for member in members:
            width = box_widths[member]
            positions[member] = (cursor + width / 2, current_y)
            cursor += width + _COL_GAP
        previous_layer = layer
    canvas_height = int(
        (max((pos[1] for pos in positions.values()), default=_BOX_H / 2)) + _BOX_H / 2
    )
    return canvas_width, canvas_height, positions


def _marker_suffix(
    nodes: Sequence[str], edges: Sequence[tuple[str, str]], aria_label: str
) -> str:
    payload = "\n".join(
        [aria_label, *nodes, *[f"{source}->{target}" for source, target in edges]]
    )
    return sha1(payload.encode("utf-8")).hexdigest()[:10]


def _block_diagram_defs(marker_suffix: str) -> str:
    arrow_id = f"block-arrow-{marker_suffix}"
    danger_id = f"block-arrow-danger-{marker_suffix}"
    return (
        "<defs>"
        f'<marker id="{arrow_id}" viewBox="0 0 10 10" refX="8.2" refY="5" '
        'markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="var(--border-strong)" '
        'fill-opacity="0.52"/></marker>'
        f'<marker id="{danger_id}" viewBox="0 0 10 10" refX="8.2" refY="5" '
        'markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="var(--danger)" '
        'fill-opacity="0.72"/></marker>'
        "</defs>"
    )


def _marker_url(*, marker_suffix: str, danger: bool) -> str:
    marker = "block-arrow-danger" if danger else "block-arrow"
    return f"url(#{marker}-{marker_suffix})"


def _spread_x(center_x: float, box_width: int, rank: int, count: int) -> float:
    """Distribute *count* edge endpoints across a box edge, ordered by *rank*."""
    if count <= 1:
        return center_x
    span = min(box_width * _FAN_SPREAD_FRAC, _FAN_SPREAD_STEP * (count - 1))
    return center_x - span / 2 + rank * (span / (count - 1))


def _rank_endpoints(
    edges: Sequence[tuple[str, str]],
    positions: Mapping[str, tuple[float, float]],
    *,
    by_key: int,
    sort_key: int,
) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    groups: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        groups.setdefault(edge[by_key], []).append(edge)
    for group in groups.values():
        group.sort(key=lambda edge: positions[edge[sort_key]][0])
    rank = {
        edge: index for group in groups.values() for index, edge in enumerate(group)
    }
    count = {node: len(group) for node, group in groups.items()}
    return rank, count


def _rank_lanes(
    edges: Sequence[tuple[str, str]],
    positions: Mapping[str, tuple[float, float]],
) -> tuple[dict[tuple[str, str], int], dict[tuple[int, int], int]]:
    groups: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for edge in edges:
        sy = round(positions[edge[0]][1])
        ty = round(positions[edge[1]][1])
        groups.setdefault((sy, ty), []).append(edge)
    for group in groups.values():
        group.sort(
            key=lambda edge: (positions[edge[0]][0], positions[edge[1]][0], edge)
        )
    rank = {
        edge: index for group in groups.values() for index, edge in enumerate(group)
    }
    count = {key: len(group) for key, group in groups.items()}
    return rank, count


def _lane_offset(rank: int, count: int) -> float:
    if count <= 1:
        return 0.0
    return (rank - (count - 1) / 2) * _LANE_STEP


def _curved_vertical_path(
    exit_x: float,
    exit_y: float,
    entry_x: float,
    entry_y: float,
    *,
    lane: float,
) -> str:
    mid = (exit_y + entry_y) / 2 + lane
    return (
        f"M{exit_x:.1f},{exit_y:.1f} "
        f"C{exit_x:.1f},{mid:.1f} {entry_x:.1f},{mid:.1f} "
        f"{entry_x:.1f},{entry_y:.1f}"
    )


def _same_layer_path(
    source_x: float,
    source_y: float,
    target_x: float,
    target_y: float,
    source_width: int,
    target_width: int,
    *,
    lane: float,
) -> str:
    side = 1 if target_x >= source_x else -1
    exit_x = source_x + side * source_width / 2
    entry_x = target_x - side * target_width / 2
    lift = _BOX_H * 1.75 + abs(lane)
    bend_y = min(source_y, target_y) - lift
    return (
        f"M{exit_x:.1f},{source_y:.1f} "
        f"C{exit_x + side * 24:.1f},{bend_y:.1f} "
        f"{entry_x - side * 24:.1f},{bend_y:.1f} "
        f"{entry_x:.1f},{target_y:.1f}"
    )


def _render_block_edges(
    edges: Sequence[tuple[str, str]],
    positions: Mapping[str, tuple[float, float]],
    box_widths: Mapping[str, int],
    box_heights: Mapping[str, int],
    *,
    danger_edges: AbstractSet[tuple[str, str]],
    weight_fn: Callable[[tuple[str, str]], int] | None,
    marker_suffix: str,
) -> list[str]:
    out_rank, out_count = _rank_endpoints(edges, positions, by_key=0, sort_key=1)
    in_rank, in_count = _rank_endpoints(edges, positions, by_key=1, sort_key=0)
    lane_rank, lane_count = _rank_lanes(edges, positions)
    rendered: list[str] = []
    for source, target in edges:
        sx, sy = positions[source]
        tx, ty = positions[target]
        lane_key = (round(sy), round(ty))
        lane = _lane_offset(lane_rank[(source, target)], lane_count[lane_key])
        if ty > sy + box_heights[source]:
            exit_x = _spread_x(
                sx, box_widths[source], out_rank[(source, target)], out_count[source]
            )
            entry_x = _spread_x(
                tx, box_widths[target], in_rank[(source, target)], in_count[target]
            )
            path = _curved_vertical_path(
                exit_x,
                sy + box_heights[source] / 2,
                entry_x,
                ty - box_heights[target] / 2,
                lane=lane,
            )
        elif ty < sy - box_heights[source]:
            exit_x = _spread_x(
                sx, box_widths[source], out_rank[(source, target)], out_count[source]
            )
            entry_x = _spread_x(
                tx, box_widths[target], in_rank[(source, target)], in_count[target]
            )
            path = _curved_vertical_path(
                exit_x,
                sy - box_heights[source] / 2,
                entry_x,
                ty + box_heights[target] / 2,
                lane=lane,
            )
        else:
            path = _same_layer_path(
                sx,
                sy,
                tx,
                ty,
                box_widths[source],
                box_widths[target],
                lane=lane,
            )
        is_danger = (source, target) in danger_edges
        stroke = "var(--danger)" if is_danger else "var(--border-strong)"
        opacity = "0.66" if is_danger else "0.34"
        weight = weight_fn((source, target)) if weight_fn is not None else 1
        marker_url = _marker_url(marker_suffix=marker_suffix, danger=is_danger)
        rendered.append(
            f'<path class="dep-edge" '
            f'data-source="{_escape_html(source)}" '
            f'data-target="{_escape_html(target)}" '
            f'd="{path}" fill="none" stroke="{stroke}" stroke-opacity="{opacity}" '
            'stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-width="{_edge_stroke_width(weight)}" '
            f'marker-end="{marker_url}">'
            "<title>"
            f"{_escape_html(source)} → {_escape_html(target)}</title></path>"
        )
    return rendered


def _render_block_nodes(
    nodes: Sequence[str],
    positions: Mapping[str, tuple[float, float]],
    box_widths: Mapping[str, int],
    style_fn: Callable[[str], BlockNodeStyle],
) -> list[str]:
    rendered: list[str] = []
    for node in nodes:
        cx, cy = positions[node]
        width = box_widths[node]
        x = cx - width / 2
        y = cy - _BOX_H / 2
        style = style_fn(node)
        label = _short_label(node, _LABEL_MAX)
        parts: list[str] = []
        if style.ring:
            parts.append(
                f'<rect class="block-node-ring" data-node="{_escape_html(node)}" '
                f'x="{x - 3:.1f}" y="{y - 3:.1f}" '
                f'width="{width + 6:.1f}" height="{_BOX_H + 6:.1f}" rx="8" '
                f'fill="none" stroke="{style.ring}" stroke-width="2"/>'
            )
        dash = ' stroke-dasharray="4,3"' if style.dashed else ""
        parts.append(
            f'<rect class="block-node" data-node="{_escape_html(node)}" '
            f'x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{_BOX_H}" rx="6" '
            f'fill="{style.fill}" stroke="{style.stroke}" stroke-width="1.2"{dash}/>'
        )
        parts.append(
            f'<text class="block-node-label" data-node="{_escape_html(node)}" '
            f'x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" fill="{style.text_fill}"'
            f"{_label_fit_attrs(label, width)}>"
            f"<title>{_escape_html(style.title or node)}</title>"
            f"{_escape_html(label)}</text>"
        )
        rendered.append("".join(parts))
    return rendered


def render_block_diagram(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    *,
    style_fn: Callable[[str], BlockNodeStyle],
    aria_label: str,
    danger_edges: AbstractSet[tuple[str, str]] = frozenset(),
    edge_weight_fn: Callable[[tuple[str, str]], int] | None = None,
) -> str:
    """Render a layered block diagram for *nodes* / *edges* as a single SVG."""
    in_degree, out_degree = _build_degree_maps(nodes, edges)
    layer_groups = _build_layer_groups(nodes, edges, in_degree, out_degree)
    box_widths = {node: _box_width(_short_label(node, _LABEL_MAX)) for node in nodes}
    box_heights = dict.fromkeys(nodes, _BOX_H)
    degree = {node: in_degree.get(node, 0) + out_degree.get(node, 0) for node in nodes}
    width, height, positions = _layout_block_diagram(
        layer_groups, box_widths, degree=degree
    )
    marker_suffix = _marker_suffix(nodes, edges, aria_label)

    edge_svg = _render_block_edges(
        edges,
        positions,
        box_widths,
        box_heights,
        danger_edges=danger_edges,
        weight_fn=edge_weight_fn,
        marker_suffix=marker_suffix,
    )
    node_svg = _render_block_nodes(nodes, positions, box_widths, style_fn)
    vb_w = width + _BLOCK_PAD * 2
    vb_h = height + _BLOCK_PAD * 2
    if len(nodes) >= _WIDE_NODE_LIMIT or vb_w >= 980:
        density = "wide"
        render_width = min(max(round(vb_w * 1.08), 1040), _WIDE_RENDER_MAX)
        svg_style = f"width:100%;max-width:{render_width}px"
    elif len(nodes) > _COMPACT_NODE_LIMIT:
        density = "comfortable"
        render_width = min(max(round(vb_w * 1.18), 900), _COMFORTABLE_RENDER_MAX)
        svg_style = f"width:100%;max-width:{render_width}px"
    else:
        density = "compact"
        render_width = min(round(vb_w * 1.45), _COMPACT_RENDER_MAX)
        svg_style = f"width:100%;max-width:{render_width}px"
    return (
        '<div class="dep-graph-wrap">'
        f'<svg viewBox="{-_BLOCK_PAD} {-_BLOCK_PAD} {vb_w} {vb_h}" '
        'class="dep-graph-svg" '
        f'data-graph-density="{density}" role="img" '
        'preserveAspectRatio="xMidYMid meet" '
        f'style="{svg_style}" '
        f'aria-label="{_escape_html(aria_label)}">'
        f"{_block_diagram_defs(marker_suffix)}{''.join(edge_svg)}{''.join(node_svg)}"
        "</svg></div>"
    )
