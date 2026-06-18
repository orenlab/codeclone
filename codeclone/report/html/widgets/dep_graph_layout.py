# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared dependency-graph SVG layout primitives.

Layout = topological depth; arrows = import direction (``source`` → ``target``).
Both the Dependencies tab (``sections/_dependencies.py``) and the Module map tab
(``sections/_module_map.py``) draw precomputed nodes/edges through these helpers,
so the SVG geometry stays identical across panels.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from codeclone.utils.coerce import as_sequence

from ..primitives.escape import _escape_html
from .badges import _short_label

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


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
    *,
    in_degree: Mapping[str, int],
    out_degree: Mapping[str, int],
) -> tuple[int, int, int, dict[str, tuple[float, float]]]:
    num_layers = max(layer_groups.keys(), default=0) + 1
    max_per_layer = max((len(members) for members in layer_groups.values()), default=1)
    pad_x, pad_y = 56.0, 36.0
    prefer_horizontal = num_layers >= 6 and num_layers > max_per_layer + 2

    def _ordered_members(members: Sequence[str]) -> list[str]:
        if not prefer_horizontal or len(members) < 3:
            return list(members)
        ranked = sorted(
            members,
            key=lambda node: (
                -(in_degree.get(node, 0) + out_degree.get(node, 0)),
                node,
            ),
        )
        center = (len(ranked) - 1) / 2
        slot_order = sorted(
            range(len(ranked)),
            key=lambda index: (abs(index - center), index),
        )
        ordered = [""] * len(ranked)
        for node, slot in zip(ranked, slot_order, strict=False):
            ordered[slot] = node
        return ordered

    if prefer_horizontal:
        width = max(920, min(1600, num_layers * 118 + max_per_layer * 28 + 180))
        height = max(300, max_per_layer * 84 + 104)
    else:
        width = max(600, min(1200, max_per_layer * 70 + 140))
        height = max(260, num_layers * 80 + 80)

    positions: dict[str, tuple[float, float]] = {}
    for layer_index in range(num_layers):
        members = layer_groups.get(layer_index, [])
        count = len(members)
        if prefer_horizontal:
            members = _ordered_members(members)
            layer_step = (width - 2 * pad_x) / max(1, num_layers - 1)
            x = pad_x + layer_index * layer_step
            fan = min(14.0, layer_step * 0.12)
            offset_unit = fan / max(1, count - 1)
            center = (count - 1) / 2
            for index, node in enumerate(members):
                y = pad_y + (index + 0.5) * ((height - 2 * pad_y) / max(1, count))
                positions[node] = (x + (index - center) * offset_unit, y)
            continue

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
        '<polygon points="0 0,10 3.5,0 7" '
        'fill="var(--border-strong)" fill-opacity="0.5"/></marker>'
        '<marker id="dep-arrow-cycle" viewBox="0 0 10 7" refX="10" refY="3.5" '
        'markerWidth="5" markerHeight="4" orient="auto-start-reverse">'
        '<polygon points="0 0,10 3.5,0 7" '
        'fill="var(--danger)" fill-opacity="0.7"/></marker>'
        '<filter id="glow"><feGaussianBlur stdDeviation="2.5" result="g"/>'
        '<feMerge><feMergeNode in="g"/>'
        '<feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
    )


def _build_cycle_edges(dep_cycles: Sequence[object]) -> set[tuple[str, str]]:
    cycle_edges: set[tuple[str, str]] = set()
    for cycle in dep_cycles:
        parts = [str(part) for part in as_sequence(cycle)]
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
            f'data-source="{_escape_html(source)}" '
            f'data-target="{_escape_html(target)}" '
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
    prefer_horizontal: bool,
) -> tuple[list[str], list[str]]:
    nodes_svg: list[str] = []
    labels_svg: list[str] = []
    rotate_labels = prefer_horizontal or max_per_layer > 6

    for node in nodes:
        x, y = positions[node]
        radius = node_radii[node]
        degree = in_degree.get(node, 0) + out_degree.get(node, 0)
        label = _short_label(node)
        is_cycle = node in cycle_node_set
        is_hub = degree >= hub_threshold and degree > 2
        is_secondary = not is_hub and not is_cycle

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
            f'<circle class="dep-node" data-node="{_escape_html(node)}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{fill}" fill-opacity="{fill_opacity}" {extra}/>'
        )

        font_size = "10" if is_hub else ("8" if is_secondary else "9")
        if rotate_labels:
            label_x = (
                x + radius + (4 if is_secondary else 6 if prefer_horizontal else 0)
            )
            label_y = (
                y - radius - (1 if is_secondary else 2 if prefer_horizontal else 6)
            )
            labels_svg.append(
                f'<text class="dep-label" data-node="{_escape_html(node)}" '
                f'x="0" y="0" font-size="{font_size}" text-anchor="start" '
                f'transform="translate({label_x:.1f},{label_y:.1f}) rotate(-45)">'
                f"<title>{_escape_html(node)}</title>{_escape_html(label)}</text>"
            )
            continue

        labels_svg.append(
            f'<text class="dep-label" data-node="{_escape_html(node)}" '
            f'x="{x:.1f}" y="{y - radius - (4 if is_secondary else 5):.1f}" '
            f'font-size="{font_size}" text-anchor="middle">'
            f"<title>{_escape_html(node)}</title>{_escape_html(label)}</text>"
        )

    return nodes_svg, labels_svg
