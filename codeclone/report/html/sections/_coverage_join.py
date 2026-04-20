# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Coverage Join HTML helpers for Quality tab rendering."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..primitives.escape import _escape_html
from ..widgets.badges import _micro_badges, _stat_card, _tab_empty_info
from ..widgets.glossary import glossary_tip
from ..widgets.tables import render_rows_table

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def coverage_join_quality_count(ctx: ReportContext) -> int:
    coverage_summary = _coverage_join_summary(ctx)
    if str(coverage_summary.get("status", "")).strip() != "ok":
        return 0
    return _as_int(coverage_summary.get("coverage_hotspots")) + _as_int(
        coverage_summary.get("scope_gap_hotspots")
    )


def coverage_join_quality_summary(ctx: ReportContext) -> dict[str, object]:
    return dict(_coverage_join_summary(ctx))


def render_coverage_join_panel(ctx: ReportContext) -> str:
    metrics_map = _as_mapping(getattr(ctx, "metrics_map", {}))
    coverage_join = _as_mapping(metrics_map.get("coverage_join"))
    coverage_summary = _as_mapping(coverage_join.get("summary"))
    if not coverage_summary:
        return ""

    status = str(coverage_summary.get("status", "")).strip()
    if status != "ok":
        source = _source_label(str(coverage_summary.get("source", "")).strip())
        invalid_reason_val = coverage_summary.get("invalid_reason")
        invalid_reason = (
            invalid_reason_val.strip() if isinstance(invalid_reason_val, str) else ""
        )
        detail_parts: list[str] = []
        if source:
            detail_parts.append(f"Source: {_escape_html(source)}")
        if invalid_reason:
            detail_parts.append(
                f'<code class="tab-empty-reason">{_escape_html(invalid_reason)}</code>'
            )
        return _tab_empty_info(
            "Coverage Join is unavailable for this run.",
            detail_html="<br>".join(detail_parts) if detail_parts else None,
        )

    cards = [
        _status_card(coverage_summary),
        _overall_coverage_card(coverage_summary),
        _coverage_hotspots_card(coverage_summary),
        _scope_gaps_card(coverage_summary),
        _measured_units_card(coverage_summary),
    ]

    return (
        f'<div class="stat-cards">{"".join(cards)}</div>'
        + '<h3 class="subsection-title">Coverage review items</h3>'
        + render_rows_table(
            headers=("Function", "Location", "CC", "Status", "Coverage", "Risk"),
            rows=_coverage_join_table_rows(ctx, coverage_join),
            empty_message=_coverage_join_empty_message(),
            empty_description=_coverage_join_empty_description(),
            raw_html_headers=("Location",),
            ctx=ctx,
        )
    )


def _coverage_join_summary(ctx: ReportContext) -> Mapping[str, object]:
    metrics_map = _as_mapping(getattr(ctx, "metrics_map", {}))
    coverage_join = _as_mapping(metrics_map.get("coverage_join"))
    return _as_mapping(coverage_join.get("summary"))


def _status_card(coverage_summary: Mapping[str, object]) -> str:
    source = str(coverage_summary.get("source", "")).strip()
    return _stat_card(
        "Status",
        "Joined",
        detail=_micro_badges(("source", _source_label(source))) if source else "",
        value_tone="good",
        css_class="meta-item",
        glossary_tip_fn=glossary_tip,
    )


def _overall_coverage_card(coverage_summary: Mapping[str, object]) -> str:
    review_items = _as_int(coverage_summary.get("coverage_hotspots")) + _as_int(
        coverage_summary.get("scope_gap_hotspots")
    )
    return _stat_card(
        "Overall coverage",
        _format_permille_pct(coverage_summary.get("overall_permille")),
        detail=_micro_badges(
            ("covered", _as_int(coverage_summary.get("overall_covered_lines"))),
            ("executable", _as_int(coverage_summary.get("overall_executable_lines"))),
        ),
        value_tone="warn" if review_items > 0 else "good",
        css_class="meta-item",
        glossary_tip_fn=glossary_tip,
    )


def _coverage_hotspots_card(coverage_summary: Mapping[str, object]) -> str:
    hotspots = _as_int(coverage_summary.get("coverage_hotspots"))
    threshold = _as_int(coverage_summary.get("hotspot_threshold_percent"))
    return _stat_card(
        "Coverage hotspots",
        hotspots,
        detail=_micro_badges(("threshold", f"< {threshold}%")),
        value_tone="bad" if hotspots > 0 else "good",
        css_class="meta-item",
        glossary_tip_fn=glossary_tip,
    )


def _scope_gaps_card(coverage_summary: Mapping[str, object]) -> str:
    scope_gaps = _as_int(coverage_summary.get("scope_gap_hotspots"))
    return _stat_card(
        "Scope gaps",
        scope_gaps,
        detail=_micro_badges(
            (
                "not mapped",
                _as_int(coverage_summary.get("missing_from_report_units")),
            ),
        ),
        value_tone="warn" if scope_gaps > 0 else "good",
        css_class="meta-item",
        glossary_tip_fn=glossary_tip,
    )


def _measured_units_card(coverage_summary: Mapping[str, object]) -> str:
    return _stat_card(
        "Measured units",
        _as_int(coverage_summary.get("measured_units")),
        detail=_micro_badges(("units", _as_int(coverage_summary.get("units")))),
        css_class="meta-item",
        glossary_tip_fn=glossary_tip,
    )


def _coverage_join_table_rows(
    ctx: ReportContext,
    coverage_family: Mapping[str, object],
) -> list[tuple[str, str, str, str, str, str]]:
    review_items = [
        _as_mapping(item)
        for item in _as_sequence(coverage_family.get("items"))
        if bool(_as_mapping(item).get("coverage_review_item"))
        or bool(_as_mapping(item).get("coverage_hotspot"))
        or bool(_as_mapping(item).get("scope_gap_hotspot"))
    ]
    return [
        (
            str(item.get("qualname", "")).strip() or "(unknown)",
            _location_cell_html(ctx, item),
            str(_as_int(item.get("cyclomatic_complexity"))),
            _status_cell_label(item),
            _coverage_cell_label(item),
            str(item.get("risk", "low")).strip() or "low",
        )
        for item in review_items[:50]
    ]


def _coverage_join_empty_message() -> str:
    return "No medium/high-risk functions need joined-coverage follow-up."


def _coverage_join_empty_description() -> str:
    return (
        "No risky functions were below threshold or missing from the supplied "
        "coverage.xml."
    )


def _location_cell_html(ctx: ReportContext, item: Mapping[str, object]) -> str:
    relative_path = str(item.get("relative_path", "")).strip()
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    line_label = (
        f"{relative_path}:{start_line}"
        if start_line > 0
        else (relative_path or "(unknown)")
    )
    if end_line > start_line > 0:
        line_label = f"{relative_path}:{start_line}-{end_line}"
    file_target = (
        f"{ctx.scan_root.rstrip('/')}/{relative_path}"
        if ctx.scan_root and relative_path
        else relative_path
    )
    return (
        f'<a class="ide-link" data-file="{_escape_html(file_target)}" '
        f'data-line="{start_line if start_line > 0 else 1}">'
        f"{_escape_html(line_label)}</a>"
    )


def _status_cell_label(item: Mapping[str, object]) -> str:
    if bool(item.get("scope_gap_hotspot")):
        return "not in coverage.xml"
    if bool(item.get("coverage_hotspot")):
        return "below threshold"
    return str(item.get("coverage_status", "")).replace("_", " ").strip() or "n/a"


def _coverage_cell_label(item: Mapping[str, object]) -> str:
    if bool(item.get("scope_gap_hotspot")):
        return "n/a"
    return _format_permille_pct(item.get("coverage_permille"))


def _format_permille_pct(value: object) -> str:
    return f"{_as_int(value) / 10.0:.1f}%"


def _source_label(source: str) -> str:
    name = Path(source).name
    return name or source
