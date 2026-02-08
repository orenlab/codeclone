"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Any

from . import __version__
from ._html_escape import _escape_attr, _escape_html, _meta_display
from ._html_snippets import (
    _FileCache,
    _prefix_css,
    _pygments_css,
    _render_code_block,
    _try_pygments,
    pairwise,
)
from .templates import FONT_CSS_URL, REPORT_TEMPLATE

__all__ = [
    "_FileCache",
    "_prefix_css",
    "_pygments_css",
    "_render_code_block",
    "_try_pygments",
    "build_html_report",
    "pairwise",
]

# ============================
# HTML report builder
# ============================


def _group_sort_key(items: list[dict[str, Any]]) -> tuple[int]:
    return (-len(items),)


def build_html_report(
    *,
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    segment_groups: dict[str, list[dict[str, Any]]],
    report_meta: dict[str, Any] | None = None,
    title: str = "CodeClone Report",
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    file_cache = _FileCache()

    func_sorted = sorted(
        func_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )
    block_sorted = sorted(
        block_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )
    segment_sorted = sorted(
        segment_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )

    has_any = bool(func_sorted) or bool(block_sorted) or bool(segment_sorted)

    # Pygments CSS (scoped). Use modern GitHub-like styles when available.
    # We scope per theme to support toggle without reloading.
    pyg_dark_raw = _pygments_css("github-dark")
    if not pyg_dark_raw:
        pyg_dark_raw = _pygments_css("monokai")
    pyg_light_raw = _pygments_css("github-light")
    if not pyg_light_raw:
        pyg_light_raw = _pygments_css("friendly")

    pyg_dark = _prefix_css(pyg_dark_raw, "html[data-theme='dark']")
    pyg_light = _prefix_css(pyg_light_raw, "html[data-theme='light']")

    # ============================
    # Icons (Inline SVG)
    # ============================
    def _svg_icon(size: int, stroke_width: str, body: str) -> str:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="{stroke_width}" '
            'stroke-linecap="round" stroke-linejoin="round">'
            f"{body}</svg>"
        )

    ICONS = {
        "search": _svg_icon(
            16,
            "2.5",
            '<circle cx="11" cy="11" r="8"></circle>'
            '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
        ),
        "clear": _svg_icon(
            16,
            "2.5",
            '<line x1="18" y1="6" x2="6" y2="18"></line>'
            '<line x1="6" y1="6" x2="18" y2="18"></line>',
        ),
        "chev_down": _svg_icon(
            16,
            "2.5",
            '<polyline points="6 9 12 15 18 9"></polyline>',
        ),
        # ICON_CHEV_RIGHT = (
        #     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
        #     'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
        #     'stroke-linejoin="round">'
        #     '<polyline points="9 18 15 12 9 6"></polyline>'
        #     "</svg>"
        # )
        "theme": _svg_icon(
            16,
            "2",
            '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>',
        ),
        "check": _svg_icon(
            48,
            "2",
            '<polyline points="20 6 9 17 4 12"></polyline>',
        ),
        "prev": _svg_icon(
            16,
            "2",
            '<polyline points="15 18 9 12 15 6"></polyline>',
        ),
        "next": _svg_icon(
            16,
            "2",
            '<polyline points="9 18 15 12 9 6"></polyline>',
        ),
    }

    # ----------------------------
    # Section renderer
    # ----------------------------

    def render_section(
        section_id: str,
        section_title: str,
        groups: list[tuple[str, list[dict[str, Any]]]],
        pill_cls: str,
    ) -> str:
        if not groups:
            return ""

        # build group DOM with data-search (for fast client-side search)
        out: list[str] = [
            f'<section id="{section_id}" class="section" data-section="{section_id}">',
            '<div class="section-head">',
            f"<h2>{_escape_html(section_title)} "
            f'<span class="pill {pill_cls}" data-count-pill="{section_id}">'
            f"{len(groups)} groups</span></h2>",
            f"""
<div class="section-toolbar"
     role="toolbar"
     aria-label="{_escape_attr(section_title)} controls">
  <div class="toolbar-left">
    <div class="search-wrap">
      <span class="search-ico">{ICONS["search"]}</span>
      <input class="search"
             id="search-{section_id}"
             placeholder="Search..."
             autocomplete="off" />
      <button class="btn ghost"
              type="button"
              data-clear="{section_id}"
              title="Clear search">{ICONS["clear"]}</button>
    </div>
    <div class="segmented">
      <button class="btn seg"
              type="button"
              data-collapse-all="{section_id}">Collapse</button>
      <button class="btn seg"
              type="button"
              data-expand-all="{section_id}">Expand</button>
    </div>
  </div>

  <div class="toolbar-right">
    <div class="pager">
      <button class="btn"
              type="button"
              data-prev="{section_id}">{ICONS["prev"]}</button>
      <span class="page-meta" data-page-meta="{section_id}">Page 1</span>
      <button class="btn"
              type="button"
              data-next="{section_id}">{ICONS["next"]}</button>
    </div>
    <select class="select" data-pagesize="{section_id}" title="Groups per page">
      <option value="5">5 / page</option>
      <option value="10" selected>10 / page</option>
      <option value="20">20 / page</option>
      <option value="50">50 / page</option>
    </select>
  </div>
</div>
""",
            "</div>",  # section-head
            '<div class="section-body">',
        ]

        for idx, (gkey, items) in enumerate(groups, start=1):
            search_parts: list[str] = [str(gkey)]
            for it in items:
                search_parts.append(str(it.get("qualname", "")))
                search_parts.append(str(it.get("filepath", "")))
            search_blob = " ".join(search_parts).lower()
            search_blob_escaped = _escape_attr(search_blob)

            out.append(
                f'<div class="group" data-group="{section_id}" '
                f'data-group-index="{idx}" '
                f'data-group-key="{_escape_attr(gkey)}" '
                f'data-search="{search_blob_escaped}">'
            )

            out.append(
                '<div class="group-head">'
                '<div class="group-left">'
                f'<button class="chev" type="button" aria-label="Toggle group" '
                f'data-toggle-group="{section_id}-{idx}">{ICONS["chev_down"]}</button>'
                f'<div class="group-title">Group #{idx}</div>'
                f'<span class="pill small {pill_cls}">{len(items)} items</span>'
                "</div>"
                '<div class="group-right">'
                f'<code class="gkey" title="{_escape_attr(gkey)}">'
                f"{_escape_html(gkey)}</code>"
                "</div>"
                "</div>"
            )

            out.append(f'<div class="items" id="group-body-{section_id}-{idx}">')

            for i in range(0, len(items), 2):
                row_items = items[i : i + 2]
                out.append('<div class="item-pair">')

                for item in row_items:
                    snippet = _render_code_block(
                        filepath=item["filepath"],
                        start_line=int(item["start_line"]),
                        end_line=int(item["end_line"]),
                        file_cache=file_cache,
                        context=context_lines,
                        max_lines=max_snippet_lines,
                    )

                    qualname = _escape_html(item["qualname"])
                    qualname_attr = _escape_attr(item["qualname"])
                    filepath = _escape_html(item["filepath"])
                    filepath_attr = _escape_attr(item["filepath"])
                    start_line = int(item["start_line"])
                    end_line = int(item["end_line"])
                    out.append(
                        f'<div class="item" data-qualname="{qualname_attr}" '
                        f'data-filepath="{filepath_attr}" '
                        f'data-start-line="{start_line}" '
                        f'data-end-line="{end_line}">'
                        f'<div class="item-head" title="{qualname_attr}">'
                        f"{qualname}</div>"
                        f'<div class="item-file" '
                        f'title="{filepath_attr}:{start_line}-{end_line}">'
                        f"{filepath}:{start_line}-{end_line}"
                        f"</div>"
                        f"{snippet.code_html}"
                        "</div>"
                    )

                out.append("</div>")  # item-pair

            out.append("</div>")  # items
            out.append("</div>")  # group

        out.append("</div>")  # section-body
        out.append("</section>")
        return "\n".join(out)

    # ============================
    # HTML Rendering
    # ============================

    empty_state_html = ""
    if not has_any:
        empty_state_html = f"""
<div class="empty">
  <div class="empty-card">
    <div class="empty-icon">{ICONS["check"]}</div>
    <h2>No code clones detected</h2>
    <p>
      No structural, block-level, or segment-level duplication was found above
      configured thresholds.
    </p>
    <p class="muted">This usually indicates healthy abstraction boundaries.</p>
  </div>
</div>
"""

    func_section = render_section(
        "functions", "Function clones", func_sorted, "pill-func"
    )
    block_section = render_section("blocks", "Block clones", block_sorted, "pill-block")
    segment_section = render_section(
        "segments", "Segment clones", segment_sorted, "pill-segment"
    )

    meta = dict(report_meta or {})
    meta_rows: list[tuple[str, Any]] = [
        ("CodeClone", meta.get("codeclone_version", __version__)),
        ("Python", meta.get("python_version")),
        ("Baseline", meta.get("baseline_path")),
        ("Baseline version", meta.get("baseline_version")),
        ("Baseline schema", meta.get("baseline_schema_version")),
        ("Baseline Python", meta.get("baseline_python_version")),
        ("Baseline loaded", meta.get("baseline_loaded")),
        ("Baseline status", meta.get("baseline_status")),
    ]
    if "cache_path" in meta:
        meta_rows.append(("Cache path", meta.get("cache_path")))
    if "cache_used" in meta:
        meta_rows.append(("Cache used", meta.get("cache_used")))

    meta_attrs = " ".join(
        [
            (
                'data-codeclone-version="'
                f'{_escape_attr(meta.get("codeclone_version", __version__))}"'
            ),
            f'data-python-version="{_escape_attr(meta.get("python_version"))}"',
            f'data-baseline-path="{_escape_attr(meta.get("baseline_path"))}"',
            f'data-baseline-version="{_escape_attr(meta.get("baseline_version"))}"',
            f'data-baseline-schema-version="{_escape_attr(meta.get("baseline_schema_version"))}"',
            f'data-baseline-python-version="{_escape_attr(meta.get("baseline_python_version"))}"',
            f'data-baseline-loaded="{_escape_attr(_meta_display(meta.get("baseline_loaded")))}"',
            f'data-baseline-status="{_escape_attr(meta.get("baseline_status"))}"',
            f'data-cache-path="{_escape_attr(meta.get("cache_path"))}"',
            f'data-cache-used="{_escape_attr(_meta_display(meta.get("cache_used")))}"',
        ]
    )

    def _meta_row_class(label: str) -> str:
        if label in {"Baseline", "Cache path"}:
            return "meta-row meta-row-wide"
        return "meta-row"

    def _is_path_field(label: str) -> bool:
        """Check if field contains a file path."""
        return label in {"Baseline", "Cache path"}

    def _is_bool_field(label: str) -> bool:
        """Check if field contains a boolean value."""
        return label in {"Baseline loaded", "Cache used"}

    def _format_meta_value(label: str, value: Any) -> str:
        """Format meta value with appropriate styling."""
        display_val = _meta_display(value)

        # Boolean fields with badge styling
        if _is_bool_field(label):
            if isinstance(value, bool):
                badge_class = "meta-bool-true" if value else "meta-bool-false"
                badge_text = "true" if value else "false"
                return f'<span class="meta-bool {badge_class}">{badge_text}</span>'
            else:
                return '<span class="meta-bool meta-bool-na">n/a</span>'

        # Path fields with tooltip on hover
        if _is_path_field(label) and display_val != "n/a":
            escaped_path = _escape_html(display_val)
            return (
                f'<span class="meta-path">'
                f"{escaped_path}"
                f'<span class="meta-path-tooltip">{escaped_path}</span>'
                f"</span>"
            )

        # Regular fields
        return _escape_html(display_val)

    meta_rows_html = "".join(
        (
            f'<div class="{_meta_row_class(label)}">'
            f"<dt>{_escape_html(label)}</dt>"
            f"<dd>{_format_meta_value(label, value)}</dd>"
            "</div>"
        )
        for label, value in meta_rows
    )

    # Chevron icon for toggle
    chevron_icon = (
        '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M19 9l-7 7-7-7"/>'
        "</svg>"
    )

    # Count non-n/a fields for badge
    non_na_count = sum(1 for _, val in meta_rows if _meta_display(val) != "n/a")

    report_meta_html = (
        f'<section class="meta-panel" id="report-meta" {meta_attrs}>'
        '<div class="meta-header">'
        '<div class="meta-header-left">'
        f'<div class="meta-toggle">{chevron_icon}</div>'
        '<h3 class="meta-title">Report Provenance</h3>'
        f'<span class="meta-badge">{non_na_count} fields</span>'
        "</div>"
        "</div>"
        '<div class="meta-content">'
        '<div class="meta-body">'
        f'<dl class="meta-grid">{meta_rows_html}</dl>'
        "</div>"
        "</div>"
        "</section>"
    )

    return REPORT_TEMPLATE.substitute(
        title=_escape_html(title),
        version=__version__,
        pyg_dark=pyg_dark,
        pyg_light=pyg_light,
        report_meta_html=report_meta_html,
        empty_state_html=empty_state_html,
        func_section=func_section,
        block_section=block_section,
        segment_section=segment_section,
        icon_theme=ICONS["theme"],
        font_css_url=FONT_CSS_URL,
    )
