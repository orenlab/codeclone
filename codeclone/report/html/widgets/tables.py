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
    _level_chip_html,
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

#: Headers whose value is a judgement, and therefore keeps the semantic palette.
_VERDICT_HEADERS = {"risk", "severity"}
#: Headers whose value is a position on a scale. Confidence is how strong the
#: evidence is and effort is what a fix costs: a high-confidence row is a
#: reliable finding, not an error, so neither borrows the risk colours.
_LEVEL_HEADERS = {"confidence", "effort"}
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
    "confidence": "100px",
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
    "source": "136px",
    # Identity columns: wide enough for a qualname, bounded so one long value
    # cannot set the width of the table.
    "name": "220px",
    "module": "240px",
    "function": "240px",
    "class": "240px",
    "group": "300px",
    "owner": "420px",
    "sink": "240px",
    "canonical owner": "220px",
    "contract": "170px",
    "file": "170px",
    "location": "190px",
    "cycle": "300px",
    "longest chain": "300px",
    # Value and provenance columns.
    "occurrences": "110px",
    "resolution": "126px",
    "why": "190px",
    "producers": "170px",
    "propose": "110px",
    "rule": "120px",
    "pattern": "180px",
    "reason": "110px",
    # Wide enough for a test module chip per line: this column answers "what
    # breaks if I delete this", and at a hundred pixels it answered in a
    # fifteen-line wrap of dotted paths.
    "held by tests": "220px",
    "capability": "150px",
    "evidence": "180px",
    "review": "170px",
    "coverage": "110px",
    "signals": "190px",
    "fan-in/out": "110px",
    "score": "130px",
    "groups": "84px",
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

#: Width reserved by a declared column type. A chip column sized by its content
#: makes the whole table jump between rows, so the type carries the width and a
#: future chip column arrives sized rather than needing its own header entry.
#: An explicit ``_COL_WIDTHS`` entry still wins.
_CELL_TYPE_WIDTHS = {
    "chips": "200px",
    "status": "124px",
    "source_kind": "104px",
    "code": "240px",
    "meter": "110px",
    "meter_neutral": "110px",
}

#: The bound a column takes when nothing else claims one. A table is sized to
#: its content, so a column with no declared width is sized by whatever the data
#: happens to be, and one long value pushes the whole table past its wrap. This
#: is the floor that makes that impossible: an unregistered header still gets a
#: width, so a new table cannot reintroduce a self-sizing column.
_DEFAULT_COL_WIDTH = "160px"


#: A provenance column is lifted onto the meta band only while it names few
#: enough values that the line can still state all of them.
_META_COLUMN_MAX_VALUES = 4

#: Header of the column that carries how many identical rows were counted.
_COUNT_HEADER = "Groups"


#: How the canonical document ordered the rows a panel drew, in the words the
#: meta band prints. A panel states one of these only when the document really
#: sorted that family that way -- a cut described as "worst first" over rows
#: ordered by file path would be a claim the report cannot back.
ORDER_WORST_FIRST = "worst first"
ORDER_BY_LOCATION = "in file order"


def graded_coverage(
    label: str,
    all_items: Sequence[Mapping[str, object]],
    shown_items: Sequence[Mapping[str, object]],
    *,
    field: str,
    value: str,
) -> tuple[str, int, int] | None:
    """How many of the graded rows survived the cut, counted from one grade.

    Both counts read the same published field on the same rows, so the band
    can never disagree with the table it sits on: it is the document's own
    per-row grade, counted over the rows the panel held and over the rows it
    drew. The summary's own count of the same population is deliberately not
    used -- reading one number here and a different one from the cards would
    be two counters for one fact, which is the defect this report keeps
    paying for.

    Returns ``None`` when nothing carries the grade: a panel with no high-risk
    row has no coverage question to answer.
    """

    def _graded(item: Mapping[str, object]) -> bool:
        return str(item.get(field, "")).strip().lower() == value

    population = sum(1 for item in all_items if _graded(item))
    if not population:
        return None
    return (label, sum(1 for item in shown_items if _graded(item)), population)


def row_cut_note_html(
    *,
    total: int,
    shown: int,
    ordering: str,
    covered: tuple[str, int, int] | None = None,
) -> str:
    """State a table's cut on its meta band, or say nothing when none happened.

    A table that renders fifty of nine hundred rows in silence leaves "there
    are fifty" and "you are looking at fifty of them" as the same page. This
    is the one sentence that tells them apart, and every cut table in the
    report builds it here rather than wording its own.

    ``ordering`` names the order the *document* put the rows in, so the reader
    knows whether the rows that fell off are the least interesting ones or
    merely the ones whose paths sort late. ``covered`` answers the sharper
    question a card above a cut table raises -- "it says thirty-eight
    high-risk; are all thirty-eight here?" -- as ``(label, in_table, in_all)``,
    which :func:`graded_coverage` counts.

    Silent when the table drew everything it had: a band on every table would
    be noise, and the panels that *do* cut are the ones a reader needs warned
    about. Nothing here compares against a number of the renderer's own -- both
    comparisons are between two measured counts.
    """

    if total <= shown:
        return ""
    parts = [f"Showing {shown} of {total} rows", ordering]
    if covered is not None:
        label, in_table, in_all = covered
        parts.append(
            f"all {in_all} {label} rows"
            if in_table >= in_all
            else f"{in_table} of {in_all} {label} rows"
        )
    joined = " · ".join(part for part in parts if part)
    return f'<span class="table-meta-count">{_escape_html(joined)}</span>'


def _identity_cell_html(qualname: str) -> str:
    """Draw a ``module:symbol`` identity as the symbol over its module.

    The identity column is the one a reader acts on -- it names what to
    delete, split or move -- and it was the one column drawn as a single
    nowrap line cut off with an ellipsis, so on this repository twenty-six
    of thirty dead-code rows hid the end of the name they existed to show.
    The symbol now leads on its own line and the module qualifies it under,
    in the muted mono the rest of the report uses for paths; nothing is
    elided, and a name without a module separator is drawn as it came.
    """

    module, separator, symbol = qualname.rpartition(":")
    if not separator or not module:
        return _escape_html(qualname)
    return (
        f'<span class="ident-symbol">{_escape_html(symbol)}</span>'
        f'<span class="ident-module">{_escape_html(module)}</span>'
    )


def _breakable_path_html(path: str) -> str:
    """Escape a path and let it break after each separator, never mid-word."""

    return _escape_html(path).replace("/", "/<wbr>")


def _column_values(rows: Sequence[Sequence[str]], index: int) -> list[str]:
    return [row[index] if index < len(row) else "" for row in rows]


def _drop_empty_columns(
    headers: list[str],
    rows: list[list[str]],
) -> tuple[list[str], list[list[str]]]:
    """Remove every column that is empty in every row.

    An all-empty column states nothing, so it renders nothing -- not a header
    over thirteen blanks, which is what the suppressed clone table shipped.
    """
    keep = [
        index
        for index in range(len(headers))
        if any(value.strip() for value in _column_values(rows, index))
    ]
    if len(keep) == len(headers):
        return headers, rows
    return (
        [headers[index] for index in keep],
        [[row[index] if index < len(row) else "" for index in keep] for row in rows],
    )


def _lift_meta_columns(
    headers: list[str],
    rows: list[list[str]],
    meta_columns: Collection[str],
) -> tuple[list[str], list[list[str]], list[tuple[str, list[str]]]]:
    """Move near-constant provenance columns onto the table's meta band.

    A column is lifted only when it names few enough values to state them all,
    and only when removing it leaves every row still distinguishable. A column
    that tells two rows apart carries per-row information and stays a column,
    whatever the call site declared -- that is what keeps the lift lossless.
    """
    wanted = {header.lower() for header in meta_columns}
    lifted = [
        index
        for index, header in enumerate(headers)
        if header.lower() in wanted
        and 0
        < len(dict.fromkeys(_column_values(rows, index)))
        <= _META_COLUMN_MAX_VALUES
    ]
    if not lifted:
        return headers, rows, []
    keep = [index for index in range(len(headers)) if index not in set(lifted)]
    reduced = [
        tuple(row[index] if index < len(row) else "" for index in keep) for row in rows
    ]
    if len(set(reduced)) < len({tuple(row) for row in rows}):
        return headers, rows, []
    parts = [
        (
            headers[index],
            [
                value
                for value in dict.fromkeys(_column_values(rows, index))
                if value.strip()
            ],
        )
        for index in lifted
    ]
    return (
        [headers[index] for index in keep],
        [list(row) for row in reduced],
        parts,
    )


def _meta_lead_html(parts: Sequence[tuple[str, Sequence[str]]]) -> str:
    """State the lifted columns once, above the rows they used to repeat in."""
    chunks = []
    for label, values in parts:
        shown = list(values[:_META_COLUMN_MAX_VALUES])
        text = ", ".join(shown)
        if len(values) > len(shown):
            text = f"{text} +{len(values) - len(shown)} more"
        chunks.append(
            f'{_escape_html(label)}: <span class="table-meta-value">'
            f"{_escape_html(text)}</span>"
        )
    return f'<span class="table-meta-lead">{" &middot; ".join(chunks)}</span>'


def table_meta_band_html(lead_html: str, count_html: str) -> str:
    """One band per table: what introduces the rows left, what qualifies them right.

    Both halves are optional and a table with neither renders none, but they
    share a band when both exist -- two stacked strips of the same width above
    one table read as two tables that lost their headers.
    """

    if not lead_html and not count_html:
        return ""
    return f'<div class="table-meta">{lead_html}{count_html}</div>'


def _count_identical_rows(
    headers: list[str],
    rows: list[list[str]],
) -> tuple[list[str], list[list[str]]]:
    """Collapse byte-identical rows into one row carrying how many there were.

    Seven rows a reader cannot tell apart say nothing the count does not. The
    rows are identical across every rendered column, so the count is the only
    fact the repetition was carrying.
    """
    counts: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = tuple(row)
        counts[key] = counts.get(key, 0) + 1
    if len(counts) == len(rows):
        return headers, rows
    return (
        [*headers, _COUNT_HEADER],
        [
            [*key, f"&times;{count}" if count > 1 else ""]
            for key, count in counts.items()
        ],
    )


def _condense_rows(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    meta_columns: Collection[str],
    count_identical: bool,
    has_details: bool,
) -> tuple[list[str], list[list[str]], str]:
    """Drop what says nothing, lift provenance, and count what repeats.

    Skipped entirely for a table with detail rows: those are index-aligned to
    the rows, so removing or merging a row would open the wrong panel.
    """
    working_headers = list(headers)
    working_rows = [list(row) for row in rows]
    if has_details:
        return working_headers, working_rows, ""
    working_headers, working_rows = _drop_empty_columns(working_headers, working_rows)
    working_headers, working_rows, lifted = _lift_meta_columns(
        working_headers, working_rows, meta_columns
    )
    if count_identical:
        working_headers, working_rows = _count_identical_rows(
            working_headers, working_rows
        )
    return working_headers, working_rows, _meta_lead_html(lifted) if lifted else ""


def render_rows_table(
    *,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    empty_message: str,
    empty_description: str | None = "Nothing to report - keep up the good work.",
    raw_html_headers: Collection[str] = (),
    column_types: Mapping[str, str] | None = None,
    row_details: Sequence[str] | None = None,
    meta_columns: Collection[str] = (),
    count_identical_rows: bool = False,
    row_cut_note: str = "",
    family: str,
    ctx: ReportContext | None = None,
) -> str:
    """Render a data table with badges, tooltips, and col sizing.

    *family* names the report family owning these columns and is what the
    header glossary is asked with: ``Kind`` is a symbol type in dead code, a
    clone kind in clones, and a violation kind in semantic authority.

    *column_types* maps a header to a typed cell renderer: ``"score"`` (indigo
    progress bar + value), ``"status"`` (candidate-status pill), or ``"chips"``
    (comma-separated values as compact chips). Typed columns own their own
    badge markup, so the table stays the single rendering authority.

    *meta_columns* names provenance columns -- why the rows are here rather
    than what they are -- which are lifted onto the meta band when they are
    near-constant and lifting keeps every row distinguishable.
    *count_identical_rows* collapses rows that are identical across every
    rendered column into one row carrying the count.

    *row_cut_note* is the caller's :func:`row_cut_note_html` statement of how
    many rows it handed over out of how many it held. The panel builds it
    because only the panel knows the population: the rows arriving here are
    already cut, and this renderer condenses them further, so neither end of
    the count is recoverable from ``rows``.
    """
    if not rows:
        return _tab_empty(empty_message, description=empty_description)

    headers, rows, lead_html = _condense_rows(
        headers,
        rows,
        meta_columns=meta_columns,
        count_identical=count_identical_rows,
        has_details=bool(row_details),
    )

    lower_headers = [h.lower() for h in headers]
    raw_html_set = {h.lower() for h in raw_html_headers} | {_COUNT_HEADER.lower()}
    typed_cols = {h.lower(): t for h, t in (column_types or {}).items()}

    # Meter columns self-scale: each bar fills relative to that column's max.
    meter_max: dict[int, float] = {}
    for col_idx, header in enumerate(lower_headers):
        if typed_cols.get(header) not in ("meter", "meter_neutral"):
            continue
        values = [_safe_abs_float(row[col_idx]) for row in rows if col_idx < len(row)]
        meter_max[col_idx] = max([*values, 0.0])

    # colgroup: an explicit header width wins, else the declared type's width,
    # else the default bound. Every column declares one: the table is sized to
    # its content, so a column that declares nothing is sized by the data and
    # one long value drags the whole table past its wrap.
    cg = ["<colgroup>"]
    for h in lower_headers:
        w = (
            _COL_WIDTHS.get(h)
            or _CELL_TYPE_WIDTHS.get(typed_cols.get(h, ""))
            or _DEFAULT_COL_WIDTH
        )
        cg.append(f'<col style="width:{w}">')
    cg.append("</colgroup>")

    # thead
    th_parts = [
        f"<th>{_escape_html(header)}{glossary_tip(header, family=family)}</th>"
        for header in headers
    ]

    # tbody
    def _td(col_idx: int, cell: str) -> str:
        h = lower_headers[col_idx] if col_idx < len(lower_headers) else ""
        cell_type = typed_cols.get(h)
        if cell_type in ("meter", "meter_neutral"):
            colmax = meter_max.get(col_idx, 0.0)
            fraction = _safe_abs_float(cell) / colmax if colmax > 0 else 0.0
            meter = _metric_meter_html(
                cell,
                fraction=fraction,
                neutral=cell_type == "meter_neutral",
            )
            return f'<td class="col-num">{meter}</td>'
        if cell_type in _CELL_RENDERERS:
            cls = _CELL_TYPE_CLS[cell_type]
            return f'<td class="{cls}">{_CELL_RENDERERS[cell_type](cell)}</td>'
        cls = _COL_CLS.get(h, "")
        cls_attr = f' class="{cls}"' if cls else ""
        if h in raw_html_set:
            return f"<td{cls_attr}>{cell}</td>"
        if h in _VERDICT_HEADERS:
            return f"<td{cls_attr}>{_quality_badge_html(cell)}</td>"
        if h in _LEVEL_HEADERS:
            return f"<td{cls_attr}>{_level_chip_html(cell)}</td>"
        if h in _PATH_HEADERS and ctx is not None:
            short = ctx.relative_path(cell)
            return (
                f'<td{cls_attr} title="{_escape_html(cell)}">'
                f'<a class="ide-link" data-file="{_escape_html(cell)}" data-line="1">'
                f"{_breakable_path_html(short)}</a></td>"
            )
        if cls == "col-name":
            # The full ``module:symbol`` stays on the cell: the two lines are
            # how it is read, the attribute is how it is searched and copied.
            return (
                f'<td{cls_attr} title="{_escape_html(cell)}">'
                f"{_identity_cell_html(cell)}</td>"
            )
        return f"<td{cls_attr}>{_escape_html(cell)}</td>"

    # A row may carry a detail panel. It cannot live inside a cell: a six-line
    # TOML block in the narrowest column is cut mid-word and drags a horizontal
    # scrollbar across the table. It becomes a row of its own spanning every
    # column, opened by the summary that stays in the cell -- see the
    # tr:has(details[open]) rule, which needs no script.
    details = tuple(row_details or ())
    span = len(lower_headers)

    def _row(index: int, row: Sequence[str]) -> str:
        cells = "".join(_td(i, cell) for i, cell in enumerate(row))
        detail = details[index] if index < len(details) else ""
        if not detail:
            return f"<tr>{cells}</tr>"
        return (
            f"<tr>{cells}</tr>"
            f'<tr class="detail-row"><td colspan="{span}">'
            f'<div class="detail-panel">{detail}</div>'
            "</td></tr>"
        )

    body_html = "".join(_row(index, row) for index, row in enumerate(rows))

    return (
        f"{table_meta_band_html(lead_html, row_cut_note)}"
        '<div class="table-wrap"><table class="table">'
        f"{''.join(cg)}"
        f"<thead><tr>{''.join(th_parts)}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table></div>"
    )
