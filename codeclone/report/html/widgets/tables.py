# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Generic table renderer for metric/finding tables."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from ..primitives.escape import _escape_html
from .badges import (
    _chips_html,
    _code_chip_html,
    _metric_meter_html,
    _quality_badge_html,
    _score_bar_html,
    _source_kind_badge_html,
    _status_pill_html,
    _tab_empty,
)
from .glossary import glossary_tip

if TYPE_CHECKING:
    from .._context import ReportContext

_RISK_HEADERS = {"risk", "confidence", "severity", "effort"}
_PATH_HEADERS = {"file", "location"}

_COL_WIDTHS: dict[str, str] = {
    "cc": "62px",
    "cbo": "62px",
    "lcom4": "70px",
    "nesting": "76px",
    "line": "60px",
    "length": "68px",
    "methods": "80px",
    "fields": "68px",
    "priority": "74px",
    "risk": "78px",
    "confidence": "94px",
    "severity": "82px",
    "effort": "78px",
    "category": "100px",
    "kind": "76px",
    "steps": "120px",
    "coupled classes": "360px",
    "fan-in": "96px",
    "fan-out": "100px",
    "loc": "100px",
    "complexity total": "136px",
    "source": "104px",
}

_COL_CLS: dict[str, str] = {}
for _h in ("function", "class", "name"):
    _COL_CLS[_h] = "col-name"
for _h in ("file", "location"):
    _COL_CLS[_h] = "col-path"
for _h in (
    "cc",
    "cbo",
    "lcom4",
    "nesting",
    "line",
    "length",
    "methods",
    "fields",
    "priority",
):
    _COL_CLS[_h] = "col-num"
for _h in ("risk", "confidence", "severity", "effort"):
    _COL_CLS[_h] = "col-badge"
for _h in ("category", "kind"):
    _COL_CLS[_h] = "col-cat"
for _h in ("cycle", "longest chain", "title", "coupled classes"):
    _COL_CLS[_h] = "col-wide"
_COL_CLS["steps"] = "col-steps"


_CELL_RENDERERS = {
    "score": _score_bar_html,
    "status": _status_pill_html,
    "chips": _chips_html,
    "source_kind": _source_kind_badge_html,
    "code": _code_chip_html,
}


def _safe_abs_float(value: object) -> float:
    try:
        return abs(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0.0


_CELL_TYPE_CLS = {
    "score": "col-score",
    "status": "col-badge",
    "chips": "col-chips",
    "source_kind": "col-badge",
    "code": "col-code",
}


def render_rows_table(
    *,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    empty_message: str,
    empty_description: str | None = "Nothing to report - keep up the good work.",
    raw_html_headers: Collection[str] = (),
    column_types: Mapping[str, str] | None = None,
    ctx: ReportContext | None = None,
) -> str:
    """Render a data table with badges, tooltips, and col sizing.

    *column_types* maps a header to a typed cell renderer: ``"score"`` (indigo
    progress bar + value), ``"status"`` (candidate-status pill), or ``"chips"``
    (comma-separated values as compact chips). Typed columns own their own
    badge markup, so the table stays the single rendering authority.
    """
    if not rows:
        return _tab_empty(empty_message, description=empty_description)

    lower_headers = [h.lower() for h in headers]
    raw_html_set = {h.lower() for h in raw_html_headers}
    typed_cols = {h.lower(): t for h, t in (column_types or {}).items()}

    # Meter columns self-scale: each bar fills relative to that column's max.
    meter_max: dict[int, float] = {}
    for col_idx, header in enumerate(lower_headers):
        if typed_cols.get(header) != "meter":
            continue
        values = [_safe_abs_float(row[col_idx]) for row in rows if col_idx < len(row)]
        meter_max[col_idx] = max([*values, 0.0])

    # colgroup
    cg = ["<colgroup>"]
    for h in lower_headers:
        w = _COL_WIDTHS.get(h)
        cg.append(f'<col style="width:{w}">' if w else "<col>")
    cg.append("</colgroup>")

    # thead
    th_parts = [
        f"<th>{_escape_html(header)}{glossary_tip(header)}</th>" for header in headers
    ]

    # tbody
    def _td(col_idx: int, cell: str) -> str:
        h = lower_headers[col_idx] if col_idx < len(lower_headers) else ""
        cell_type = typed_cols.get(h)
        if cell_type == "meter":
            colmax = meter_max.get(col_idx, 0.0)
            fraction = _safe_abs_float(cell) / colmax if colmax > 0 else 0.0
            meter = _metric_meter_html(cell, fraction=fraction)
            return f'<td class="col-num">{meter}</td>'
        if cell_type in _CELL_RENDERERS:
            cls = _CELL_TYPE_CLS[cell_type]
            return f'<td class="{cls}">{_CELL_RENDERERS[cell_type](cell)}</td>'
        cls = _COL_CLS.get(h, "")
        cls_attr = f' class="{cls}"' if cls else ""
        if h in raw_html_set:
            return f"<td{cls_attr}>{cell}</td>"
        if h in _RISK_HEADERS:
            return f"<td{cls_attr}>{_quality_badge_html(cell)}</td>"
        if h in _PATH_HEADERS and ctx is not None:
            short = ctx.relative_path(cell)
            return (
                f'<td{cls_attr} title="{_escape_html(cell)}">'
                f'<a class="ide-link" data-file="{_escape_html(cell)}" data-line="1">'
                f"{_escape_html(short)}</a></td>"
            )
        return f"<td{cls_attr}>{_escape_html(cell)}</td>"

    body_html = "".join(
        "<tr>" + "".join(_td(i, cell) for i, cell in enumerate(row)) + "</tr>"
        for row in rows
    )

    return (
        '<div class="table-wrap"><table class="table">'
        f"{''.join(cg)}"
        f"<thead><tr>{''.join(th_parts)}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table></div>"
    )
