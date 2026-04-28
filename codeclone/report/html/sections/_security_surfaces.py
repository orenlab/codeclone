# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Security Surfaces HTML helpers for Quality tab rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..primitives.escape import _escape_html
from ..primitives.location import location_file_target, relative_location_path
from ..widgets.badges import _micro_badges, _stat_card, _tab_empty_info
from ..widgets.components import overview_summary_item_html
from ..widgets.glossary import glossary_tip
from ..widgets.tables import render_rows_table

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def security_surfaces_quality_count(ctx: ReportContext) -> int:
    return _as_int(_security_surfaces_summary(ctx).get("items"))


def render_security_surfaces_panel(ctx: ReportContext) -> str:
    summary = _security_surfaces_summary(ctx)
    if not summary:
        return ""
    items = tuple(
        map(_as_mapping, _as_sequence(ctx.security_surfaces_map.get("items")))
    )
    if not items:
        return _tab_empty_info(
            "No security-relevant capability surfaces matched the exact registry.",
            detail_html=(
                "This inventory is report-only and focuses on exact boundary "
                "capabilities rather than vulnerability claims."
            ),
        )
    cards = [
        _stat_card(
            "Surfaces",
            _as_int(summary.get("items")),
            detail=_micro_badges(("report", "only"), ("evidence", "exact")),
            value_tone="warn" if _as_int(summary.get("items")) > 0 else "muted",
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Categories",
            _as_int(summary.get("category_count")),
            detail=_micro_badges(("modules", _as_int(summary.get("modules")))),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Production",
            _as_int(summary.get("production")),
            detail=_micro_badges(("tests", _as_int(summary.get("tests")))),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Exact items",
            _as_int(summary.get("exact_items")),
            detail=_micro_badges(("fixtures", _as_int(summary.get("fixtures")))),
            css_class="meta-item",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return (
        f'<div class="stat-cards">{"".join(cards)}</div>'
        + _security_surfaces_context_html(ctx, items)
        + '<h3 class="subsection-title">Security-relevant capability inventory</h3>'
        + render_rows_table(
            headers=(
                "Category",
                "Capability",
                "Evidence",
                "Source",
                "Location",
                "Review",
            ),
            rows=_security_surface_rows(ctx, items),
            empty_message="No exact security surfaces are available.",
            empty_description=(
                "CodeClone inventories trust-boundary capabilities but does not "
                "claim vulnerabilities or exploitability."
            ),
            raw_html_headers=("Location",),
            ctx=ctx,
        )
    )


def _security_surfaces_summary(ctx: ReportContext) -> Mapping[str, object]:
    return _as_mapping(ctx.security_surfaces_map.get("summary"))


def _security_surface_rows(
    ctx: ReportContext,
    items: tuple[Mapping[str, object], ...],
) -> list[tuple[str, str, str, str, str, str]]:
    coverage_index = _coverage_review_index(ctx)
    return [
        (
            _humanize(str(item.get("category", ""))),
            _humanize(str(item.get("capability", ""))),
            str(item.get("evidence_symbol", "")).strip() or "(unknown)",
            _humanize(str(item.get("source_kind", ""))),
            _location_cell_html(ctx, item),
            _review_cell_text(ctx, item, coverage_index=coverage_index),
        )
        for item in items[:50]
    ]


def _location_cell_html(ctx: ReportContext, item: Mapping[str, object]) -> str:
    relative_path = relative_location_path(ctx, item)
    qualname = str(item.get("qualname", "")).strip()
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    file_target = location_file_target(ctx, item, relative_path=relative_path)
    line_label = (
        f"{relative_path}:{start_line}"
        if start_line > 0
        else (relative_path or "(unknown)")
    )
    if end_line > start_line > 0:
        line_label = f"{relative_path}:{start_line}-{end_line}"
    title = qualname or line_label or "(unknown)"
    return (
        f'<a class="ide-link" data-file="{_escape_html(file_target)}" '
        f'data-line="{start_line if start_line > 0 else 1}" '
        f'title="{_escape_html(title)}">'
        f"{_escape_html(line_label)}</a>"
    )


def _security_surfaces_context_html(
    ctx: ReportContext,
    items: tuple[Mapping[str, object], ...],
) -> str:
    review_order_rows = _security_review_order_rows(ctx, items)
    return (
        '<div class="insight-banner insight-info">'
        '<div class="insight-question">How should I review this inventory?</div>'
        '<div class="insight-answer">'
        '<div class="overview-summary-grid overview-summary-grid--2col">'
        + overview_summary_item_html(
            label="How to read",
            body_html=_fact_list_html(
                (
                    ("Signal", "boundary inventory", None),
                    ("Evidence", "exact imports/calls/builtins", None),
                    ("Meaning", "inventory, not vulnerability proof", None),
                )
            ),
        )
        + overview_summary_item_html(
            label="Review order",
            body_html=_fact_list_html(review_order_rows),
        )
        + "</div></div></div>"
    )


def _security_review_order_rows(
    ctx: ReportContext,
    items: tuple[Mapping[str, object], ...],
) -> tuple[tuple[str, str, str | None], ...]:
    production_callable_count = sum(
        1 for item in items if _is_production_callable(item)
    )
    non_callable_count = sum(
        1 for item in items if str(item.get("location_scope", "")).strip() != "callable"
    )
    coverage_index = _coverage_review_index(ctx)
    coverage_overlap_total = 0
    coverage_scope_gaps = 0
    coverage_hotspots = 0
    for item in items:
        if not _is_production_callable(item):
            continue
        cues = _coverage_review_cues(ctx, item, coverage_index=coverage_index)
        if cues["overlap"]:
            coverage_overlap_total += 1
            coverage_scope_gaps += 1 if cues["scope_gap_hotspot"] else 0
            coverage_hotspots += 1 if cues["coverage_hotspot"] else 0

    return (
        (
            "Start with",
            (
                f"{production_callable_count} "
                f"{_pluralize(production_callable_count, 'production callable')}"
                if production_callable_count > 0
                else "production module rows only"
            ),
            "warn" if production_callable_count > 0 else None,
        ),
        (
            "Coverage join",
            _coverage_join_review_text(
                ctx,
                overlap_total=coverage_overlap_total,
                scope_gaps=coverage_scope_gaps,
                hotspots=coverage_hotspots,
            ),
            "warn" if coverage_overlap_total > 0 else None,
        ),
        (
            "Then review",
            (
                f"{non_callable_count} "
                f"{_pluralize(non_callable_count, 'module/class inventory row')}"
                if non_callable_count > 0
                else "no inventory-only rows"
            ),
            None,
        ),
    )


def _coverage_join_review_text(
    ctx: ReportContext,
    *,
    overlap_total: int,
    scope_gaps: int,
    hotspots: int,
) -> str:
    coverage_join = _as_mapping(_as_mapping(ctx.metrics_map).get("coverage_join"))
    coverage_summary = _as_mapping(coverage_join.get("summary"))
    if str(coverage_summary.get("status", "")).strip() != "ok":
        return "unavailable for this run"
    if overlap_total <= 0:
        return "no overlap in current review set"
    parts = [f"{overlap_total} {_pluralize(overlap_total, 'overlap')}"]
    if scope_gaps > 0:
        parts.append(f"{scope_gaps} {_pluralize(scope_gaps, 'scope gap')}")
    if hotspots > 0:
        parts.append(f"{hotspots} {_pluralize(hotspots, 'low-coverage overlap')}")
    return " · ".join(parts)


def _review_cell_text(
    ctx: ReportContext,
    item: Mapping[str, object],
    *,
    coverage_index: Mapping[tuple[str, str], Mapping[str, bool]],
) -> str:
    location_scope = str(item.get("location_scope", "")).strip()
    scope_text = _humanize(location_scope)
    if location_scope == "module":
        return f"{scope_text} · capability present"
    cues = _coverage_review_cues(ctx, item, coverage_index=coverage_index)
    if cues["scope_gap_hotspot"]:
        return f"{scope_text} · scope gap"
    if cues["coverage_hotspot"]:
        return f"{scope_text} · low coverage"
    return f"{scope_text} · exact evidence"


def _coverage_review_cues(
    ctx: ReportContext,
    item: Mapping[str, object],
    *,
    coverage_index: Mapping[tuple[str, str], Mapping[str, bool]],
) -> Mapping[str, bool]:
    relative_path = relative_location_path(ctx, item)
    qualname = str(item.get("qualname", "")).strip()
    if not relative_path or not qualname:
        return {
            "overlap": False,
            "coverage_hotspot": False,
            "scope_gap_hotspot": False,
        }
    return coverage_index.get(
        (relative_path, qualname),
        {
            "overlap": False,
            "coverage_hotspot": False,
            "scope_gap_hotspot": False,
        },
    )


def _coverage_review_index(
    ctx: ReportContext,
) -> dict[tuple[str, str], dict[str, bool]]:
    coverage_join = _as_mapping(_as_mapping(ctx.metrics_map).get("coverage_join"))
    coverage_summary = _as_mapping(coverage_join.get("summary"))
    if str(coverage_summary.get("status", "")).strip() != "ok":
        return {}
    index: dict[tuple[str, str], dict[str, bool]] = {}
    for item in map(_as_mapping, _as_sequence(coverage_join.get("items"))):
        item_key = _coverage_review_item_key(ctx, item)
        if item_key is None:
            continue
        entry = index.setdefault(
            item_key,
            {
                "overlap": True,
                "coverage_hotspot": False,
                "scope_gap_hotspot": False,
            },
        )
        entry["coverage_hotspot"] = entry["coverage_hotspot"] or bool(
            item.get("coverage_hotspot")
        )
        entry["scope_gap_hotspot"] = entry["scope_gap_hotspot"] or bool(
            item.get("scope_gap_hotspot")
        )
    return index


def _is_production_callable(item: Mapping[str, object]) -> bool:
    return (
        str(item.get("source_kind", "")).strip() == "production"
        and str(item.get("location_scope", "")).strip() == "callable"
    )


def _coverage_review_key(
    ctx: ReportContext,
    item: Mapping[str, object],
) -> tuple[str, str] | None:
    relative_path = relative_location_path(ctx, item)
    qualname = str(item.get("qualname", "")).strip()
    if not relative_path or not qualname:
        return None
    return (relative_path, qualname)


def _coverage_review_item_key(
    ctx: ReportContext,
    item: Mapping[str, object],
) -> tuple[str, str] | None:
    if not (
        bool(item.get("coverage_review_item"))
        or bool(item.get("coverage_hotspot"))
        or bool(item.get("scope_gap_hotspot"))
    ):
        return None
    return _coverage_review_key(ctx, item)


def _fact_list_html(
    rows: tuple[tuple[str, str, str | None], ...],
) -> str:
    return (
        '<div class="overview-fact-list">'
        + "".join(
            '<div class="overview-fact-row">'
            f'<span class="overview-fact-label">{_escape_html(label)}</span>'
            f'<span class="overview-fact-value'
            f'{f" overview-fact-value--{tone}" if tone else ""}">'
            f"{_escape_html(value)}</span></div>"
            for label, value, tone in rows
        )
        + "</div>"
    )


def _pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


def _humanize(value: str) -> str:
    text = value.strip().replace("_", " ")
    return text if not text else text[0].upper() + text[1:]


__all__ = [
    "render_security_surfaces_panel",
    "security_surfaces_quality_count",
]
