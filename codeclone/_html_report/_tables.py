# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Generic table renderer for metric/finding tables."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from .._html_badges import _quality_badge_html, _tab_empty
from .._html_escape import _escape_attr, _escape_html
from ._glossary import glossary_tip

if TYPE_CHECKING:
    from ._context import ReportContext

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


def render_rows_table(
    *,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    empty_message: str,
    raw_html_headers: Collection[str] = (),
    ctx: ReportContext | None = None,
) -> str:
    """Render a data table with badges, tooltips, and col sizing."""
    if not rows:
        return _tab_empty(empty_message)

    lower_headers = [h.lower() for h in headers]
    raw_html_set = {h.lower() for h in raw_html_headers}

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
        cls = _COL_CLS.get(h, "")
        cls_attr = f' class="{cls}"' if cls else ""
        if h in raw_html_set:
            return f"<td{cls_attr}>{cell}</td>"
        if h in _RISK_HEADERS:
            return f"<td{cls_attr}>{_quality_badge_html(cell)}</td>"
        if h in _PATH_HEADERS and ctx is not None:
            short = ctx.relative_path(cell)
            return (
                f'<td{cls_attr} title="{_escape_attr(cell)}">{_escape_html(short)}</td>'
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
