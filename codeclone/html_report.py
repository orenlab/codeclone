"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import html
import importlib
import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, NamedTuple, cast

from codeclone import __version__
from codeclone.errors import FileProcessingError

from .templates import FONT_CSS_URL, REPORT_TEMPLATE

# ============================
# Pairwise
# ============================


def pairwise(iterable: Iterable[Any]) -> Iterable[tuple[Any, Any]]:
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b, strict=False)


# ============================
# Code snippet infrastructure
# ============================


@dataclass(slots=True)
class _Snippet:
    filepath: str
    start_line: int
    end_line: int
    code_html: str


class _FileCache:
    __slots__ = ("_get_lines_impl", "maxsize")

    def __init__(self, maxsize: int = 128) -> None:
        self.maxsize = maxsize
        # Create a bound method with lru_cache
        # We need to cache on the method to have instance-level caching if we wanted
        # different caches per instance. But lru_cache on method actually caches
        # on the function object (class level) if not careful,
        # or we use a wrapper.
        # However, for this script, we usually have one reporter.
        # To be safe and cleaner, we can use a method that delegates to a cached
        # function, OR just use lru_cache on a method (which requires 'self' to be
        # hashable, which it is by default id).
        # But 'self' changes if we create new instances.
        # Let's use the audit's pattern: cache the implementation.

        self._get_lines_impl = lru_cache(maxsize=maxsize)(self._read_file_range)

    @staticmethod
    def _read_file_range(
        filepath: str, start_line: int, end_line: int
    ) -> tuple[str, ...]:
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            return ()

        try:

            def _read_with_errors(errors: str) -> tuple[str, ...]:
                lines: list[str] = []
                with open(filepath, encoding="utf-8", errors=errors) as f:
                    for lineno, line in enumerate(f, start=1):
                        if lineno < start_line:
                            continue
                        if lineno > end_line:
                            break
                        lines.append(line.rstrip("\n"))
                return tuple(lines)

            try:
                return _read_with_errors("strict")
            except UnicodeDecodeError:
                return _read_with_errors("replace")
        except OSError as e:
            raise FileProcessingError(f"Cannot read {filepath}: {e}") from e

    def get_lines_range(
        self, filepath: str, start_line: int, end_line: int
    ) -> tuple[str, ...]:
        return self._get_lines_impl(filepath, start_line, end_line)

    class _CacheInfo(NamedTuple):
        hits: int
        misses: int
        maxsize: int | None
        currsize: int

    def cache_info(self) -> _CacheInfo:
        return cast(_FileCache._CacheInfo, self._get_lines_impl.cache_info())


def _try_pygments(code: str) -> str | None:
    try:
        pygments = importlib.import_module("pygments")
        formatters = importlib.import_module("pygments.formatters")
        lexers = importlib.import_module("pygments.lexers")
    except ImportError:
        return None

    highlight = pygments.highlight
    formatter_cls = formatters.HtmlFormatter
    lexer_cls = lexers.PythonLexer
    result = highlight(code, lexer_cls(), formatter_cls(nowrap=True))
    return result if isinstance(result, str) else None


def _pygments_css(style_name: str) -> str:
    """
    Returns CSS for pygments tokens. Scoped to `.codebox` to avoid leaking styles.
    If Pygments is not available or style missing, returns "".
    """
    try:
        formatters = importlib.import_module("pygments.formatters")
    except ImportError:
        return ""

    try:
        formatter_cls = formatters.HtmlFormatter
        fmt = formatter_cls(style=style_name)
    except Exception:
        try:
            fmt = formatter_cls()
        except Exception:
            return ""

    try:
        # `.codebox` scope: pygments will emit selectors like `.codebox .k { ... }`
        css = fmt.get_style_defs(".codebox")
        return css if isinstance(css, str) else ""
    except Exception:
        return ""


def _prefix_css(css: str, prefix: str) -> str:
    """
    Prefix every selector block with `prefix `.
    Safe enough for pygments CSS which is mostly selector blocks and comments.
    """
    out_lines: list[str] = []
    for line in css.splitlines():
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if stripped.startswith(("/*", "*", "*/")):
            out_lines.append(line)
            continue
        # Selector lines usually end with `{
        if "{" in line:
            # naive prefix: split at "{", prefix selector part
            before, after = line.split("{", 1)
            sel = before.strip()
            if sel:
                out_lines.append(f"{prefix} {sel} {{ {after}".rstrip())
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _render_code_block(
    *,
    filepath: str,
    start_line: int,
    end_line: int,
    file_cache: _FileCache,
    context: int,
    max_lines: int,
) -> _Snippet:
    s = max(1, start_line - context)
    e = end_line + context

    if e - s + 1 > max_lines:
        e = s + max_lines - 1

    lines = file_cache.get_lines_range(filepath, s, e)

    numbered: list[tuple[bool, str]] = []
    for lineno, line in enumerate(lines, start=s):
        hit = start_line <= lineno <= end_line
        numbered.append((hit, f"{lineno:>5} | {line.rstrip()}"))

    raw = "\n".join(text for _, text in numbered)
    highlighted = _try_pygments(raw)

    if highlighted is None:
        rendered: list[str] = []
        for hit, text in numbered:
            cls = "hitline" if hit else "line"
            rendered.append(f'<div class="{cls}">{html.escape(text)}</div>')
        body = "\n".join(rendered)
    else:
        body = highlighted

    return _Snippet(
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        code_html=f'<div class="codebox"><pre><code>{body}</code></pre></div>',
    )


# ============================
# HTML report builder
# ============================


def _escape(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _group_sort_key(items: list[dict[str, Any]]) -> tuple[int, int]:
    return (
        -len(items),
        -max(int(i.get("loc") or i.get("size") or 0) for i in items),
    )


def build_html_report(
    *,
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    segment_groups: dict[str, list[dict[str, Any]]],
    title: str = "CodeClone Report",
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    file_cache = _FileCache()

    func_sorted = sorted(func_groups.items(), key=lambda kv: _group_sort_key(kv[1]))
    block_sorted = sorted(block_groups.items(), key=lambda kv: _group_sort_key(kv[1]))
    segment_sorted = sorted(
        segment_groups.items(), key=lambda kv: _group_sort_key(kv[1])
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
            f"<h2>{_escape(section_title)} "
            f'<span class="pill {pill_cls}" data-count-pill="{section_id}">'
            f"{len(groups)} groups</span></h2>",
            f"""
<div class="section-toolbar"
     role="toolbar"
     aria-label="{_escape(section_title)} controls">
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
            search_blob_escaped = html.escape(search_blob, quote=True)

            out.append(
                f'<div class="group" data-group="{section_id}" '
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
                f'<code class="gkey">{_escape(gkey)}</code>'
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

                    out.append(
                        '<div class="item">'
                        f'<div class="item-head">{_escape(item["qualname"])}</div>'
                        f'<div class="item-file">'
                        f"{_escape(item['filepath'])}:"
                        f"{item['start_line']}-{item['end_line']}"
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

    return REPORT_TEMPLATE.substitute(
        title=_escape(title),
        version=__version__,
        pyg_dark=pyg_dark,
        pyg_light=pyg_light,
        empty_state_html=empty_state_html,
        func_section=func_section,
        block_section=block_section,
        segment_section=segment_section,
        icon_theme=ICONS["theme"],
        font_css_url=FONT_CSS_URL,
    )
