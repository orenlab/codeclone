# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Overview panel renderer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _stat_card
from ..._html_escape import _escape_html
from .._components import (
    Tone,
    insight_block,
    overview_cluster_header,
    overview_section_html,
    overview_source_breakdown_html,
    overview_summary_item_html,
    overview_summary_list_html,
)
from .._glossary import glossary_tip

if TYPE_CHECKING:
    from .._context import ReportContext

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _health_gauge_html(
    score: float, grade: str, *, health_delta: int | None = None
) -> str:
    """Render an SVG ring gauge for health score."""
    if score < 0:
        return _stat_card(
            "Health",
            "n/a",
            css_class="meta-item overview-health-card",
            glossary_tip_fn=glossary_tip,
        )
    circumference = 2.0 * math.pi * 42.0
    offset = circumference * (1.0 - score / 100.0)
    if score >= 80:
        color = "var(--success)"
    elif score >= 60:
        color = "var(--warning)"
    else:
        color = "var(--error)"

    delta_html = ""
    if health_delta is not None and health_delta != 0:
        if health_delta > 0:
            cls = "health-ring-delta--up"
            sign = "+"
        else:
            cls = "health-ring-delta--down"
            sign = ""
        delta_html = f'<div class="health-ring-delta {cls}">{sign}{health_delta}</div>'

    return (
        '<div class="meta-item overview-health-card">'
        '<div class="overview-health-inner">'
        '<div class="health-ring">'
        '<svg viewBox="0 0 100 100">'
        '<circle class="health-ring-bg" cx="50" cy="50" r="42"/>'
        f'<circle class="health-ring-fg" cx="50" cy="50" r="42" '
        f'stroke="{color}" '
        f'stroke-dasharray="{circumference:.1f}" '
        f'stroke-dashoffset="{offset:.1f}"/>'
        "</svg>"
        '<div class="health-ring-label">'
        f'<div class="health-ring-score">{score:.0f}</div>'
        f'<div class="health-ring-grade">Grade {_escape_html(grade)}</div>'
        f"{delta_html}"
        "</div></div></div></div>"
    )


def _top_risk_label(item: object) -> str:
    m = _as_mapping(item)
    if m:
        label = str(m.get("label", "")).strip()
        if label:
            return label
        family = str(m.get("family", "")).strip().replace("_", " ")
        count = _as_int(m.get("count"))
        scope = str(m.get("scope", "")).strip()
        if family and count:
            return f"{count} {family}" + (f" ({scope})" if scope else "")
        return family or str(item)
    raw = str(item).strip()
    if raw.startswith("{") and raw.endswith("}"):
        return ""
    return raw


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

    # KPI cards
    kpis = [
        _stat_card(
            "Clone Groups",
            ctx.clone_groups_total,
            detail=(
                f"{len(ctx.func_sorted)} func · "
                f"{len(ctx.block_sorted)} block · "
                f"{len(ctx.segment_sorted)} seg"
            ),
            tip="Detected code clone groups by detection level",
        ),
        _stat_card(
            "High Complexity",
            complexity_high_risk,
            detail=(
                f"avg {complexity_summary.get('average', 'n/a')} · "
                f"max {complexity_summary.get('max', 'n/a')}"
            ),
            tip="Functions with cyclomatic complexity above threshold",
            delta_new=_new_complexity,
        ),
        _stat_card(
            "High Coupling",
            coupling_high_risk,
            detail=(
                f"avg {coupling_summary.get('average', 'n/a')} · "
                f"max {coupling_summary.get('max', 'n/a')}"
            ),
            tip="Classes with high coupling between objects (CBO)",
            delta_new=_new_coupling,
        ),
        _stat_card(
            "Low Cohesion",
            cohesion_low,
            detail=(
                f"avg {cohesion_summary.get('average', 'n/a')} · "
                f"max {cohesion_summary.get('max', 'n/a')}"
            ),
            tip="Classes with low internal cohesion (high LCOM4)",
        ),
        _stat_card(
            "Dep. Cycles",
            dependency_cycle_count,
            detail=f"max depth {dependency_max_depth}",
            tip="Circular dependencies between project modules",
            delta_new=_new_cycles,
        ),
        _stat_card(
            "Dead Code",
            dead_total,
            detail=f"{dead_high_conf} high-confidence",
            tip="Potentially unused functions, classes, or imports",
            delta_new=_new_dead,
        ),
    ]

    # Executive summary
    top_risks = [
        label
        for item in _as_sequence(ctx.overview_data.get("top_risks"))
        if (label := _top_risk_label(item))
    ]
    _top_risks_body = (
        overview_summary_list_html(tuple(top_risks))
        if top_risks
        else '<div class="overview-summary-value muted">No risks detected.</div>'
    )
    executive = (
        '<section class="overview-cluster">'
        + overview_cluster_header(
            "Executive Summary",
            "Project-wide context derived from the full scanned root.",
        )
        + '<div class="overview-summary-grid overview-summary-grid--2col">'
        + overview_summary_item_html(label="Top risks", body_html=_top_risks_body)
        + overview_summary_item_html(
            label="Source breakdown",
            body_html=overview_source_breakdown_html(
                _as_mapping(ctx.overview_data.get("source_breakdown"))
            ),
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
        + "".join(kpis)
        + "</div>"
        + executive
        + overview_section_html(
            title="Highest Spread",
            subtitle="Findings that touch the widest surface area first.",
            cards=_as_sequence(ctx.overview_data.get("highest_spread")),
            empty_message="No spread-heavy findings were recorded.",
        )
        + overview_section_html(
            title="Production Hotspots",
            subtitle="Runtime-facing hotspots across production code.",
            cards=_as_sequence(ctx.overview_data.get("production_hotspots")),
            empty_message="No production-coded hotspots were identified.",
        )
        + overview_section_html(
            title="Test/Fixture Hotspots",
            subtitle="Context-rich hotspots rooted in tests and fixtures.",
            cards=_as_sequence(ctx.overview_data.get("test_fixture_hotspots")),
            empty_message="No hotspots from tests or fixtures were identified.",
        )
    )
