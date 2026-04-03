# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Overview panel renderer."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _source_kind_badge_html, _stat_card
from ..._html_escape import _escape_html
from .._components import (
    Tone,
    insight_block,
    overview_cluster_header,
    overview_source_breakdown_html,
    overview_summary_item_html,
)
from .._glossary import glossary_tip

if TYPE_CHECKING:
    from .._context import ReportContext

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

_DIRECTORY_BUCKET_LABELS: dict[str, str] = {
    "all": "All Findings",
    "clones": "Clone Groups",
    "structural": "Structural Findings",
    "complexity": "High Complexity",
    "cohesion": "Low Cohesion",
    "coupling": "High Coupling",
    "dead_code": "Dead Code",
    "dependency": "Dependency Cycles",
}
_DIRECTORY_BUCKET_ORDER: tuple[str, ...] = (
    "all",
    "clones",
    "structural",
    "complexity",
    "cohesion",
    "coupling",
    "dead_code",
    "dependency",
)
_DIRECTORY_KIND_LABELS: dict[str, str] = {
    "clones": "clones",
    "structural": "structural",
    "dead_code": "dead code",
    "complexity": "complexity",
    "cohesion": "cohesion",
    "coupling": "coupling",
    "dependency": "dependency",
}
_GOD_MODULE_REASON_LABELS: dict[str, str] = {
    "size_pressure": "size pressure",
    "dependency_pressure": "dependency pressure",
    "hub_like_shape": "hub-like shape",
    "repeated_import_pressure": "repeated import pressure",
}


def _health_gauge_html(
    score: float, grade: str, *, health_delta: int | None = None
) -> str:
    """Render an SVG ring gauge for health score with optional baseline arc."""
    if score < 0:
        return _stat_card(
            "Health",
            "n/a",
            css_class="meta-item overview-health-card",
            glossary_tip_fn=glossary_tip,
        )
    _R = 42.0
    circumference = 2.0 * math.pi * _R
    offset = circumference * (1.0 - score / 100.0)
    if score >= 75:
        color = "var(--success)"
    elif score >= 60:
        color = "var(--warning)"
    else:
        color = "var(--error)"

    # Baseline comparison arc: show where baseline was relative to current.
    # SVG circle with rotate(-90deg) starts at 12 o'clock, goes clockwise.
    # Negative stroke-dashoffset shifts the arc forward (clockwise).
    # To place an arc at P% from 12 o'clock: offset = -(C * P / 100).
    baseline_arc = ""
    if health_delta is not None and health_delta != 0:
        baseline_score = max(0.0, min(100.0, score - health_delta))
        arc_len = circumference * abs(health_delta) / 100.0
        if health_delta > 0:
            # Improvement: ghost arc from baseline to score (gained segment)
            arc_offset = -circumference * baseline_score / 100.0
            baseline_arc = (
                f'<circle class="health-ring-baseline" cx="50" cy="50" r="{_R}" '
                f'stroke="var(--success)" opacity="0.25" '
                f'stroke-dasharray="{arc_len:.1f} {circumference - arc_len:.1f}" '
                f'stroke-dashoffset="{arc_offset:.1f}"/>'
            )
        else:
            # Degradation: red arc from score to baseline (lost segment)
            arc_offset = -circumference * score / 100.0
            baseline_arc = (
                f'<circle class="health-ring-baseline" cx="50" cy="50" r="{_R}" '
                f'stroke="var(--error)" opacity="0.4" '
                f'stroke-dasharray="{arc_len:.1f} {circumference - arc_len:.1f}" '
                f'stroke-dashoffset="{arc_offset:.1f}"/>'
            )

    delta_html = ""
    if health_delta is not None and health_delta != 0:
        if health_delta > 0:
            cls = "health-ring-delta--up"
            sign = "+"
        else:
            cls = "health-ring-delta--down"
            sign = ""
        delta_html = f'<div class="health-ring-delta {cls}">{sign}{health_delta}</div>'

    # "Get Badge" button — shown for grades A, B, C
    badge_btn_html = ""
    if grade.upper() in ("A", "B", "C"):
        badge_btn_html = (
            '<button class="badge-btn" type="button" data-badge-open'
            f' data-badge-grade="{_escape_html(grade)}"'
            f' data-badge-score="{score:.0f}">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round">'
            '<rect x="3" y="3" width="18" height="18" rx="2"/>'
            '<path d="M7 7h10M7 12h10M7 17h6"/></svg>'
            " Get Badge</button>"
        )

    return (
        '<div class="meta-item overview-health-card">'
        '<div class="overview-health-inner">'
        '<div class="health-ring">'
        '<svg viewBox="0 0 100 100">'
        '<circle class="health-ring-bg" cx="50" cy="50" r="42"/>'
        f"{baseline_arc}"
        f'<circle class="health-ring-fg" cx="50" cy="50" r="42" '
        f'stroke="{color}" '
        f'stroke-dasharray="{circumference:.1f}" '
        f'stroke-dashoffset="{offset:.1f}"/>'
        "</svg>"
        '<div class="health-ring-label">'
        f'<div class="health-ring-score">{score:.0f}</div>'
        f'<div class="health-ring-grade">Grade {_escape_html(grade)}</div>'
        f"{delta_html}"
        "</div></div>"
        f"{badge_btn_html}"
        "</div></div>"
    )


# ---------------------------------------------------------------------------
# Analytics: Health Radar (pure SVG)
# ---------------------------------------------------------------------------

_RADAR_DIMENSIONS = (
    "clones",
    "complexity",
    "coupling",
    "cohesion",
    "dead_code",
    "dependencies",
    "coverage",
)

_RADAR_LABELS = {
    "clones": "Clones",
    "complexity": "Complexity",
    "coupling": "Coupling",
    "cohesion": "Cohesion",
    "dead_code": "Dead Code",
    "dependencies": "Deps",
    "coverage": "Coverage",
}

_RADAR_CX, _RADAR_CY, _RADAR_R = 200.0, 200.0, 130.0
_RADAR_LABEL_R = 155.0


def _radar_point(index: int, total: int, radius: float) -> tuple[float, float]:
    angle = 2.0 * math.pi * index / total - math.pi / 2.0
    return (
        round(_RADAR_CX + radius * math.cos(angle), 2),
        round(_RADAR_CY + radius * math.sin(angle), 2),
    )


def _radar_polygon(total: int, radius: float) -> str:
    return " ".join(
        f"{x},{y}" for x, y in (_radar_point(i, total, radius) for i in range(total))
    )


def _health_radar_svg(dimensions: dict[str, int]) -> str:
    n = len(_RADAR_DIMENSIONS)
    scores = [max(0, min(100, dimensions.get(d, 0))) for d in _RADAR_DIMENSIONS]

    # Concentric grid rings
    rings: list[str] = []
    for pct in (0.33, 0.66, 1.0):
        pts = _radar_polygon(n, _RADAR_R * pct)
        rings.append(
            f'<polygon points="{pts}" fill="none" '
            f'stroke="var(--border)" stroke-width="0.5" opacity="0.6"/>'
        )

    # Axis lines
    axes: list[str] = []
    for i in range(n):
        x, y = _radar_point(i, n, _RADAR_R)
        axes.append(
            f'<line x1="{_RADAR_CX}" y1="{_RADAR_CY}" x2="{x}" y2="{y}" '
            f'stroke="var(--border)" stroke-width="0.5" opacity="0.4"/>'
        )

    # Score polygon
    score_pts = " ".join(
        f"{x},{y}"
        for x, y in (
            _radar_point(i, n, _RADAR_R * s / 100.0) for i, s in enumerate(scores)
        )
    )
    score_poly = (
        f'<polygon points="{score_pts}" fill="var(--accent-muted)" '
        f'stroke="var(--accent-primary)" stroke-width="1.5" '
        f'stroke-linejoin="round"/>'
    )

    # Score dots
    dots: list[str] = []
    for i, s in enumerate(scores):
        x, y = _radar_point(i, n, _RADAR_R * s / 100.0)
        color = "var(--error)" if s < 60 else "var(--accent-primary)"
        dots.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="{color}"/>')

    # Labels — two lines: name + score
    labels: list[str] = []
    for i, dim in enumerate(_RADAR_DIMENSIONS):
        lx, ly = _radar_point(i, n, _RADAR_LABEL_R)
        anchor = "middle"
        dx = lx - _RADAR_CX
        if dx < -5:
            anchor = "end"
        elif dx > 5:
            anchor = "start"
        # Nudge labels outward from center for breathing room
        nudge = 18.0
        angle = math.atan2(ly - _RADAR_CY, lx - _RADAR_CX)
        lx = round(lx + nudge * math.cos(angle), 2)
        ly = round(ly + nudge * math.sin(angle), 2)
        s = scores[i]
        cls = ' class="radar-label--weak"' if s < 60 else ""
        labels.append(
            f'<text x="{lx}" y="{ly}" text-anchor="{anchor}"'
            f' dominant-baseline="central"{cls}>'
            f"{_RADAR_LABELS.get(dim, dim)}"
            f'<tspan x="{lx}" dy="14" class="radar-score">{s}</tspan>'
            f"</text>"
        )

    return (
        '<div class="health-radar">'
        '<svg viewBox="0 0 400 400" role="img" '
        'aria-label="Health dimensions radar chart">'
        + "".join(rings)
        + "".join(axes)
        + score_poly
        + "".join(dots)
        + "".join(labels)
        + "</svg></div>"
    )


# ---------------------------------------------------------------------------
# Analytics: Findings by Family (horizontal bars)
# ---------------------------------------------------------------------------


def _issue_breakdown_html(
    ctx: ReportContext,
    *,
    deltas: dict[str, int | None],
) -> str:
    """Horizontal bar chart of real issue counts with baseline awareness.

    *deltas* maps row key → new-items count (None = no baseline loaded).
    When delta == 0 the row is fully baselined and rendered muted.
    When delta > 0 the bar is split: baselined segment (muted) + new segment.
    """
    complexity_high = _as_int(
        _as_mapping(ctx.complexity_map.get("summary")).get("high_risk")
    )
    coupling_high = _as_int(
        _as_mapping(ctx.coupling_map.get("summary")).get("high_risk")
    )
    cohesion_low = _as_int(
        _as_mapping(ctx.cohesion_map.get("summary")).get("low_cohesion")
    )
    dead_total = _as_int(_as_mapping(ctx.dead_code_map.get("summary")).get("total"))
    dep_cycles = len(_as_sequence(ctx.dependencies_map.get("cycles")))
    structural = len(ctx.structural_findings)

    # (key, label, count, color)
    raw_rows: list[tuple[str, str, int, str]] = [
        ("clones", "Clone Groups", ctx.clone_groups_total, "var(--error)"),
        ("structural", "Structural", structural, "var(--warning)"),
        ("complexity", "Complexity", complexity_high, "var(--warning)"),
        ("cohesion", "Cohesion", cohesion_low, "var(--info)"),
        ("coupling", "Coupling", coupling_high, "var(--info)"),
        ("dead_code", "Dead Code", dead_total, "var(--text-muted)"),
        ("dep_cycles", "Dep. Cycles", dep_cycles, "var(--text-muted)"),
    ]
    # Filter out zeros — show only actual issues
    rows = [
        (key, label, count, color) for key, label, count, color in raw_rows if count > 0
    ]
    if not rows:
        return '<div class="overview-summary-value muted">No issues detected.</div>'

    max_count = max(c for _, _, c, _ in rows)
    parts: list[str] = []
    for key, label, count, color in rows:
        pct = round(count / max_count * 100) if max_count else 0
        delta = deltas.get(key)

        # Determine row state
        is_muted = delta is not None and delta == 0
        has_split = delta is not None and delta > 0 and count > delta

        row_cls = "families-row families-row--muted" if is_muted else "families-row"

        # Build bar: split (baselined + new) or single fill
        if has_split:
            assert delta is not None  # for type checker
            baselined_pct = round((count - delta) / max_count * 100)
            new_pct = pct - baselined_pct
            bar_html = (
                f'<span class="breakdown-bar-track">'
                f'<span class="breakdown-bar-fill breakdown-bar-fill--baselined"'
                f' style="width:{baselined_pct}%;background:{color}"></span>'
                f'<span class="breakdown-bar-fill breakdown-bar-fill--new"'
                f' style="width:{new_pct}%;background:{color}"></span>'
                f"</span>"
            )
        else:
            bar_cls = " breakdown-bar-fill--baselined" if is_muted else ""
            bar_html = (
                f'<span class="breakdown-bar-track">'
                f'<span class="breakdown-bar-fill{bar_cls}" style="'
                f"width:{pct}%;background:{color}"
                f'"></span></span>'
            )

        # Delta indicator
        delta_html = ""
        if is_muted:
            delta_html = '<span class="families-delta families-delta--ok">\u2713</span>'
        elif delta is not None and delta > 0:
            delta_html = (
                f'<span class="families-delta families-delta--new">+{delta}</span>'
            )

        parts.append(
            f'<div class="{row_cls}">'
            f'<span class="families-label">{_escape_html(label)}</span>'
            f'<span class="families-count">{count}</span>'
            f"{bar_html}{delta_html}</div>"
        )
    return '<div class="families-list">' + "".join(parts) + "</div>"


def _dir_meta_span(val: int, label: str) -> str:
    return f"<span>{val} {_escape_html(label)}</span>"


_DIR_META_SEP = '<span class="dir-hotspot-meta-sep">\u00b7</span>'


def _format_count(value: int | float) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{int(value):,}"


def _overview_fact_rows_html(facts: list[tuple[str, str]]) -> str:
    if not facts:
        return ""
    return (
        '<div class="overview-fact-list">'
        + "".join(
            '<div class="overview-fact-row">'
            f'<span class="overview-fact-label">{_escape_html(label)}</span>'
            f'<span class="overview-fact-value">{_escape_html(value)}</span>'
            "</div>"
            for label, value in facts
        )
        + "</div>"
    )


def _mb(*pairs: tuple[str, object]) -> str:
    """Render compact micro-badges for stat-card detail rows."""
    return "".join(
        f'<span class="kpi-micro">'
        f'<span class="kpi-micro-val">{_escape_html(str(v))}</span>'
        f'<span class="kpi-micro-lbl">{_escape_html(label)}</span></span>'
        for label, v in pairs
        if v is not None and str(v) != "n/a"
    )


def _run_snapshot_section(ctx: ReportContext) -> str:
    inventory = _as_mapping(getattr(ctx, "inventory_map", {}))
    if not inventory:
        return ""

    files = _as_mapping(inventory.get("files"))
    code = _as_mapping(inventory.get("code"))
    total_found = _as_int(files.get("total_found"))
    analyzed = _as_int(files.get("analyzed"))
    cached = _as_int(files.get("cached"))
    skipped = _as_int(files.get("skipped"))
    source_io_skipped = _as_int(files.get("source_io_skipped"))
    parsed_lines = _as_int(code.get("parsed_lines"))
    functions = _as_int(code.get("functions"))
    methods = _as_int(code.get("methods"))
    classes = _as_int(code.get("classes"))
    callable_total = functions + methods

    summary_parts = [
        f"{_format_count(total_found)} found",
        f"{_format_count(analyzed)} analyzed",
        f"{_format_count(cached)} cached",
        f"{_format_count(skipped + source_io_skipped)} skipped",
    ]
    facts = [
        ("Cached files", _format_count(cached)),
        ("Skipped files", _format_count(skipped + source_io_skipped)),
        ("Parsed lines", _format_count(parsed_lines)),
        ("Callables", _format_count(callable_total)),
        ("Classes", _format_count(classes)),
    ]
    return (
        '<div class="overview-summary-value">'
        f"{' · '.join(summary_parts)}"
        "</div>" + _overview_fact_rows_html(facts)
    )


def _directory_kind_meta_parts(
    kind_breakdown: Mapping[str, object],
    *,
    total_groups: int,
) -> list[str]:
    kind_rows = [
        (str(kind), _as_int(count))
        for kind, count in kind_breakdown.items()
        if _as_int(count) > 0
    ]
    kind_rows.sort(key=lambda item: (-item[1], item[0]))
    if len(kind_rows) <= 1:
        return []
    parts: list[str] = []
    for kind, count in kind_rows[:2]:
        parts.append(_dir_meta_span(count, _DIRECTORY_KIND_LABELS.get(kind, kind)))
    return parts


def _directory_hotspot_bucket_body(bucket: str, payload: Mapping[str, object]) -> str:
    items = list(map(_as_mapping, _as_sequence(payload.get("items"))))
    if not items:
        return ""
    returned = _as_int(payload.get("returned"))
    total_directories = _as_int(payload.get("total_directories"))
    has_more = bool(payload.get("has_more"))
    subtitle_html = ""
    if has_more and returned > 0 and total_directories > returned:
        subtitle_html = (
            '<div class="overview-summary-value">'
            f"top {returned} of {total_directories} directories"
            "</div>"
        )
    rows: list[str] = []
    cumulative = 0.0
    for item in items:
        path = str(item.get("path", ".")).strip() or "."
        source_scope = _as_mapping(item.get("source_scope"))
        dominant_kind = (
            str(source_scope.get("dominant_kind", "other")).strip() or "other"
        )
        share_pct = _as_float(item.get("share_pct"))
        groups = _as_int(item.get("finding_groups"))
        affected = _as_int(item.get("affected_items"))
        files = _as_int(item.get("files"))

        meta_parts = [
            _dir_meta_span(groups, "groups"),
            _dir_meta_span(affected, "items"),
            _dir_meta_span(files, "files"),
        ]
        if bucket == "all":
            meta_parts.extend(
                _directory_kind_meta_parts(
                    _as_mapping(item.get("kind_breakdown")),
                    total_groups=groups,
                )
            )

        path_html = _escape_html(path).replace("/", "/<wbr>")

        prev_pct = min(cumulative, 100.0)
        cur_pct = min(share_pct, 100.0 - prev_pct)
        cumulative += share_pct

        bar_html = (
            '<span class="dir-hotspot-bar-track">'
            f'<span class="dir-hotspot-bar-prev" style="width:{prev_pct:.1f}%"></span>'
            f'<span class="dir-hotspot-bar-cur" style="width:{cur_pct:.1f}%"></span>'
            "</span>"
        )

        rows.append(
            '<div class="dir-hotspot-entry">'
            '<div class="dir-hotspot-path">'
            f"<code>{path_html}</code>"
            f" {_source_kind_badge_html(dominant_kind)}"
            "</div>"
            f'<div class="dir-hotspot-bar-row">{bar_html}'
            f'<span class="dir-hotspot-pct">{share_pct:.1f}%</span>'
            "</div>"
            f'<div class="dir-hotspot-meta">{_DIR_META_SEP.join(meta_parts)}</div>'
            "</div>"
        )
    return subtitle_html + '<div class="dir-hotspot-list">' + "".join(rows) + "</div>"


def _directory_hotspots_section(ctx: ReportContext) -> str:
    directory_hotspots = _as_mapping(ctx.overview_data.get("directory_hotspots"))
    if not directory_hotspots:
        return ""
    cards: list[str] = []
    for bucket in _DIRECTORY_BUCKET_ORDER:
        payload = _as_mapping(directory_hotspots.get(bucket))
        body_html = _directory_hotspot_bucket_body(bucket, payload)
        if not body_html:
            continue
        cards.append(
            overview_summary_item_html(
                label=_DIRECTORY_BUCKET_LABELS.get(bucket, bucket),
                body_html=body_html,
            )
        )
    if not cards:
        return ""
    return (
        '<section class="overview-cluster">'
        + overview_cluster_header(
            "Hotspots by Directory",
            "Directories with the highest concentration of findings by category.",
        )
        + '<div class="overview-summary-grid overview-summary-grid--2col">'
        + "".join(cards)
        + "</div></section>"
    )


def _god_modules_section(ctx: ReportContext) -> str:
    god_modules = _as_mapping(getattr(ctx, "god_modules_map", {}))
    if not god_modules:
        return ""
    summary = _as_mapping(god_modules.get("summary"))
    candidates = _as_int(summary.get("candidates"))
    if candidates <= 0:
        return ""
    candidate_rows = [
        _as_mapping(item)
        for item in _as_sequence(god_modules.get("items"))
        if str(_as_mapping(item).get("candidate_status", "")).strip() == "candidate"
    ][:5]
    if not candidate_rows:
        return ""

    top_rows = candidate_rows[:4]
    rows_html: list[str] = []
    reason_counts: Counter[str] = Counter()
    for row in candidate_rows:
        for reason in _as_sequence(row.get("candidate_reasons")):
            if str(reason).strip():
                reason_counts[str(reason)] += 1

    signal_pills = "".join(
        '<span class="god-module-signal-pill">'
        f"{_escape_html(_GOD_MODULE_REASON_LABELS.get(reason, reason.replace('_', ' ')))}"
        f'<span class="god-module-signal-count">{count}</span>'
        "</span>"
        for reason, count in sorted(
            reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:4]
    )

    for row in top_rows:
        score = _as_float(row.get("score"))
        reason_labels = [
            _GOD_MODULE_REASON_LABELS.get(str(reason), str(reason).replace("_", " "))
            for reason in _as_sequence(row.get("candidate_reasons"))
            if str(reason).strip()
        ]
        relative_path = str(row.get("relative_path", "")).strip()
        if not relative_path:
            relative_path = str(row.get("module", "")).replace(".", "/") + ".py"
        fan_summary = f"{_as_int(row.get('fan_in'))}/{_as_int(row.get('fan_out'))}"
        reason_html = (
            '<div class="god-module-reasons">'
            + "".join(
                f'<span class="god-module-reason-chip">{_escape_html(label)}</span>'
                for label in reason_labels[:3]
            )
            + "</div>"
            if reason_labels
            else ""
        )
        rows_html.append(
            '<div class="god-module-entry">'
            '<div class="god-module-head">'
            '<div class="god-module-title">'
            f"<code>{_escape_html(relative_path)}</code>"
            f"{_source_kind_badge_html(str(row.get('source_kind', 'other')))}"
            "</div>"
            f'<span class="god-module-score">{score:.2f}</span>'
            "</div>"
            '<div class="god-module-metrics">'
            f"<span>{_escape_html(_format_count(_as_int(row.get('loc'))))} LOC</span>"
            f"{_DIR_META_SEP}"
            f"<span>fan-in/out {_escape_html(fan_summary)}</span>"
            f"{_DIR_META_SEP}"
            f"<span>complexity {_escape_html(str(_as_int(row.get('complexity_total'))))}</span>"
            "</div>"
            f"{reason_html}"
            "</div>"
        )

    profile_facts = [("Top score", f"{_as_float(summary.get('top_score')):.2f}")]
    average_score = _as_float(summary.get("average_score"))
    if average_score > 0:
        profile_facts.append(("Average score", f"{average_score:.2f}"))
    population_status = str(summary.get("population_status", "")).strip()
    if population_status:
        profile_facts.append(("Population", population_status.replace("_", " ")))

    profile_html = (
        '<div class="overview-summary-value">'
        f"{candidates} candidate{'s' if candidates != 1 else ''} "
        f"across {_as_int(summary.get('total'))} ranked module{'s' if _as_int(summary.get('total')) != 1 else ''}."
        "</div>"
        + _overview_fact_rows_html(profile_facts)
        + (
            f'<div class="god-module-signal-list">{signal_pills}</div>'
            if signal_pills
            else ""
        )
    )
    return (
        '<section class="overview-cluster">'
        + overview_cluster_header(
            "God Modules",
            "Report-only module hotspots derived from project-relative implementation burden and dependency pressure.",
        )
        + '<div class="overview-summary-grid overview-summary-grid--2col">'
        + overview_summary_item_html(
            label="Top candidates",
            body_html='<div class="god-module-list">' + "".join(rows_html) + "</div>",
        )
        + overview_summary_item_html(
            label="Candidate profile",
            body_html=profile_html,
        )
        + "</div></section>"
    )


def render_overview_panel(ctx: ReportContext) -> str:
    """Build the Overview tab panel HTML."""
    complexity_summary = _as_mapping(ctx.complexity_map.get("summary"))
    coupling_summary = _as_mapping(ctx.coupling_map.get("summary"))
    cohesion_summary = _as_mapping(ctx.cohesion_map.get("summary"))
    dead_code_summary = _as_mapping(ctx.dead_code_map.get("summary"))
    dep_cycles = _as_sequence(ctx.dependencies_map.get("cycles"))

    complexity_high_risk = _as_int(complexity_summary.get("high_risk"))
    coupling_high_risk = _as_int(coupling_summary.get("high_risk"))
    cohesion_low = _as_int(cohesion_summary.get("low_cohesion"))
    dependency_cycle_count = len(dep_cycles)
    dependency_max_depth = _as_int(ctx.dependencies_map.get("max_depth"))
    dead_total = _as_int(dead_code_summary.get("total"))
    dead_high_conf = _as_int(
        dead_code_summary.get("high_confidence", dead_code_summary.get("critical"))
    )
    dead_suppressed = _as_int(dead_code_summary.get("suppressed", 0))

    health_score_raw = ctx.health_map.get("score")
    health_score_known = (
        health_score_raw is not None and str(health_score_raw).strip() != ""
    )
    health_score = _as_float(health_score_raw) if health_score_known else -1.0
    health_grade = str(ctx.health_map.get("grade", "n/a"))

    # Overview answer
    def _answer_and_tone() -> tuple[str, Tone]:
        if ctx.metrics_available and health_score_known:
            ans = (
                f"Health {health_score:.0f}/100 ({health_grade}); "
                f"{ctx.clone_groups_total} clone groups; "
                f"{dead_total} dead-code items ({dead_suppressed} suppressed); "
                f"{dependency_cycle_count} dependency cycles."
            )
            if health_score >= 80.0:
                return ans, "ok"
            if health_score >= 60.0:
                return ans, "warn"
            return ans, "risk"
        if ctx.metrics_available:
            ans = (
                f"{ctx.clone_groups_total} clone groups; "
                f"{dead_total} dead-code items ({dead_suppressed} suppressed); "
                f"{dependency_cycle_count} dependency cycles."
            )
            return ans, "info"
        return (
            f"{ctx.clone_groups_total} clone groups; metrics were skipped for this run.",
            "info",
        )

    overview_answer, overview_tone = _answer_and_tone()

    # -- MetricsDiff deltas --
    md = ctx.metrics_diff
    _new_complexity = len(md.new_high_risk_functions) if md else None
    _new_coupling = len(md.new_high_coupling_classes) if md else None
    _new_dead = len(md.new_dead_code) if md else None
    _new_cycles = len(md.new_cycles) if md else None
    _health_delta = md.health_delta if md else None
    structural_count = len(ctx.structural_findings)
    structural_kind_count = len({g.finding_kind for g in ctx.structural_findings})
    clone_suggestion_count = sum(
        1 for suggestion in ctx.suggestions if suggestion.finding_family == "clones"
    )
    structural_suggestion_count = sum(
        1 for suggestion in ctx.suggestions if suggestion.finding_family == "structural"
    )
    metrics_suggestion_count = sum(
        1 for suggestion in ctx.suggestions if suggestion.finding_family == "metrics"
    )

    # Clone group novelty — show delta only when baseline comparison is active.
    # MetricsDiff presence is the reliable indicator of a loaded baseline.
    _new_clones: int | None = None
    if md is not None:
        _new_clones = sum(
            1 for gk, _ in ctx.func_sorted if gk in ctx.new_func_keys
        ) + sum(1 for gk, _ in ctx.block_sorted if gk in ctx.new_block_keys)

    _baseline_ok = (
        '<span class="kpi-micro kpi-micro--baselined">\u2713 baselined</span>'
    )

    def _baselined_detail(
        total: int,
        delta: int | None,
        detail: str,
    ) -> tuple[str, str]:
        """Return (detail_html, value_tone) accounting for baseline state.

        When baseline is loaded and all items are accepted debt, tone
        becomes 'muted' and a '✓ baselined' pill is appended.
        When baseline is loaded but new regressions exist, the accepted
        count is shown alongside the existing detail.
        """
        if delta is None or total == 0:
            return detail, "good" if total == 0 else "bad"
        if delta == 0:
            return detail + _baseline_ok, "muted"
        baselined = total - delta
        extra = ""
        if baselined > 0:
            extra = _mb(("baselined", baselined))
        return detail + extra, "bad"

    # KPI cards — compute detail + tone with baseline awareness
    _clone_detail, _clone_tone = _baselined_detail(
        ctx.clone_groups_total,
        _new_clones,
        _mb(
            ("func", len(ctx.func_sorted)),
            ("block", len(ctx.block_sorted)),
            ("seg", len(ctx.segment_sorted)),
        ),
    )
    _cx_detail, _cx_tone = _baselined_detail(
        complexity_high_risk,
        _new_complexity,
        _mb(
            ("avg", complexity_summary.get("average", "n/a")),
            ("max", complexity_summary.get("max", "n/a")),
        ),
    )
    _cp_detail, _cp_tone = _baselined_detail(
        coupling_high_risk,
        _new_coupling,
        _mb(
            ("avg", coupling_summary.get("average", "n/a")),
            ("max", coupling_summary.get("max", "n/a")),
        ),
    )
    _cy_detail, _cy_tone = _baselined_detail(
        dependency_cycle_count,
        _new_cycles,
        _mb(("depth", dependency_max_depth)),
    )
    _dc_detail, _dc_tone = _baselined_detail(
        dead_total,
        _new_dead,
        _mb(("high-conf", dead_high_conf)),
    )

    kpis = [
        _stat_card(
            "Clone Groups",
            ctx.clone_groups_total,
            detail=_clone_detail,
            tip="Detected code clone groups by detection level",
            delta_new=_new_clones,
            value_tone=_clone_tone,
        ),
        _stat_card(
            "High Complexity",
            complexity_high_risk,
            detail=_cx_detail,
            tip="Functions with cyclomatic complexity above threshold",
            value_tone=_cx_tone,
            delta_new=_new_complexity,
        ),
        _stat_card(
            "High Coupling",
            coupling_high_risk,
            detail=_cp_detail,
            tip="Classes with high coupling between objects (CBO)",
            value_tone=_cp_tone,
            delta_new=_new_coupling,
        ),
        _stat_card(
            "Low Cohesion",
            cohesion_low,
            detail=_mb(
                ("avg", cohesion_summary.get("average", "n/a")),
                ("max", cohesion_summary.get("max", "n/a")),
            ),
            tip="Classes with low internal cohesion (high LCOM4)",
            value_tone="good" if cohesion_low == 0 else "warn",
        ),
        _stat_card(
            "Dep. Cycles",
            dependency_cycle_count,
            detail=_cy_detail,
            tip="Circular dependencies between project modules",
            value_tone=_cy_tone,
            delta_new=_new_cycles,
        ),
        _stat_card(
            "Dead Code",
            dead_total,
            detail=_dc_detail,
            tip="Potentially unused functions, classes, or imports",
            value_tone=_dc_tone,
            delta_new=_new_dead,
        ),
        _stat_card(
            "Findings",
            structural_count,
            detail=_mb(("kinds", structural_kind_count)),
            tip="Active structural findings reported in production code",
            value_tone="good" if structural_count == 0 else "warn",
        ),
        _stat_card(
            "Suggestions",
            len(ctx.suggestions),
            detail=_mb(
                ("clone", clone_suggestion_count),
                ("struct", structural_suggestion_count),
                ("metric", metrics_suggestion_count),
            ),
            tip="Actionable recommendations derived from clones, findings, and metrics",
            value_tone="good" if not ctx.suggestions else "warn",
        ),
    ]

    # Build deltas map for issue breakdown baseline awareness
    _issue_deltas: dict[str, int | None] = {
        "clones": _new_clones,
        "complexity": _new_complexity,
        "coupling": _new_coupling,
        "dead_code": _new_dead,
        "dep_cycles": _new_cycles,
        # No baseline tracking for these families
        "structural": None,
        "cohesion": None,
    }

    # Executive summary: issue breakdown (sorted) + source breakdown
    executive = (
        '<section class="overview-cluster">'
        + overview_cluster_header(
            "Executive Summary",
            "Project-wide context derived from the full scanned root.",
        )
        + '<div class="overview-summary-grid overview-summary-grid--3col">'
        + overview_summary_item_html(
            label="Issue breakdown",
            body_html=_issue_breakdown_html(ctx, deltas=_issue_deltas),
        )
        + overview_summary_item_html(
            label="Source breakdown",
            body_html=overview_source_breakdown_html(
                _as_mapping(ctx.overview_data.get("source_breakdown"))
            ),
        )
        + overview_summary_item_html(
            label="Scan scope",
            body_html=_run_snapshot_section(ctx),
        )
        + "</div></section>"
    )

    health_gauge = _health_gauge_html(
        health_score, health_grade, health_delta=_health_delta
    )

    return (
        insight_block(
            question="What is the current code-health snapshot?",
            answer=overview_answer,
            tone=overview_tone,
        )
        + '<div class="overview-kpi-grid overview-kpi-grid--with-health">'
        + health_gauge
        + '<div class="overview-kpi-cards">'
        + "".join(kpis)
        + "</div>"
        + "</div>"
        + executive
        + _directory_hotspots_section(ctx)
        + _god_modules_section(ctx)
        + _analytics_section(ctx)
    )


def _analytics_section(ctx: ReportContext) -> str:
    """Build the Analytics cluster with full-width radar chart."""
    raw_dims = _as_mapping(ctx.health_map.get("dimensions"))
    dimensions = {str(k): _as_int(v) for k, v in raw_dims.items()} if raw_dims else {}
    if not dimensions:
        return ""

    radar_html = _health_radar_svg(dimensions)

    return (
        '<section class="overview-cluster">'
        + overview_cluster_header(
            "Health Profile",
            "Dimension scores across all quality axes.",
        )
        + '<div class="overview-summary-grid">'
        + overview_summary_item_html(label="Health profile", body_html=radar_html)
        + "</div></section>"
    )
