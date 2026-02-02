"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import html
import itertools
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Optional, Iterable

from codeclone import __version__


# ============================ 
# Pairwise
# ============================ 


def pairwise(iterable: Iterable[Any]) -> Iterable[tuple[Any, Any]]:
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


# ============================ 
# Code snippet infrastructure
# ============================ 


@dataclass
class _Snippet:
    filepath: str
    start_line: int
    end_line: int
    code_html: str


class _FileCache:
    def __init__(self) -> None:
        self._lines: dict[str, list[str]] = {}

    def get_lines(self, filepath: str) -> list[str]:
        if filepath not in self._lines:
            try:
                text = Path(filepath).read_text("utf-8")
            except UnicodeDecodeError:
                text = Path(filepath).read_text("utf-8", errors="replace")
            self._lines[filepath] = text.splitlines()
        return self._lines[filepath]


def _try_pygments(code: str) -> Optional[str]:
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import PythonLexer
    except Exception:
        return None

    result = highlight(code, PythonLexer(), HtmlFormatter(nowrap=True))
    return result if isinstance(result, str) else None


def _pygments_css(style_name: str) -> str:
    """
    Returns CSS for pygments tokens. Scoped to `.codebox` to avoid leaking styles.
    If Pygments is not available or style missing, returns "".
    """
    try:
        from pygments.formatters import HtmlFormatter
    except Exception:
        return ""

    try:
        fmt = HtmlFormatter(style=style_name)
    except Exception:
        try:
            fmt = HtmlFormatter()
        except Exception:
            return ""

    try:
        # `.codebox` scope: pygments will emit selectors like `.codebox .k { ... }`
        return fmt.get_style_defs(".codebox")
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
        if (
            stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.startswith("*/")
        ):
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
    lines = file_cache.get_lines(filepath)

    s = max(1, start_line - context)
    e = min(len(lines), end_line + context)

    if e - s + 1 > max_lines:
        e = s + max_lines - 1

    numbered: list[tuple[bool, str]] = []
    for lineno in range(s, e + 1):
        line = lines[lineno - 1]
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
        code_html=f'<pre class="codebox"><code>{body}</code></pre>',
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


REPORT_TEMPLATE = Template(r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>

<style>
/* ============================ 
   CodeClone UI/UX
   ============================ */

:root {
  --bg: #0d1117;
  --panel: #161b22;
  --panel2: #21262d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --border: #30363d;
  --border2: #6e7681;
  --accent: #58a6ff;
  --accent2: rgba(56, 139, 253, 0.15);
  --good: #3fb950;
  --shadow: 0 8px 24px rgba(0,0,0,0.5);
  --shadow2: 0 4px 12px rgba(0,0,0,0.2);
  --radius: 6px;
  --radius2: 8px;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
}

html[data-theme="light"] {
  --bg: #ffffff;
  --panel: #f6f8fa;
  --panel2: #eaeef2;
  --text: #24292f;
  --muted: #57606a;
  --border: #d0d7de;
  --border2: #afb8c1;
  --accent: #0969da;
  --accent2: rgba(84, 174, 255, 0.2);
  --good: #1a7f37;
  --shadow: 0 8px 24px rgba(140,149,159,0.2);
  --shadow2: 0 4px 12px rgba(140,149,159,0.1);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  line-height: 1.5;
}

.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 20px 80px;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  opacity: 0.98;
}

.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.brand .sub {
  color: var(--muted);
  font-size: 13px;
  background: var(--panel2);
  padding: 2px 8px;
  border-radius: 99px;
  font-weight: 500;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: 0.2s;
  height: 32px;
}

.btn:hover {
  border-color: var(--border2);
  background: var(--panel2);
}

.btn.ghost {
  background: transparent;
  border-color: transparent;
  padding: 4px;
  width: 28px;
  height: 28px;
}

.select {
  padding: 0 24px 0 8px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  font-size: 13px;
}

.section {
  margin-top: 32px;
}

.section-head {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 16px;
}

.section-head h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  min-width: 300px;
  height: 32px;
}
.search-wrap:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent2);
}

.search-ico {
  color: var(--muted);
  display: flex;
}

.search {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}

.segmented {
  display: inline-flex;
  background: var(--panel2);
  padding: 2px;
  border-radius: 6px;
}

.btn.seg {
  border: none;
  background: transparent;
  height: 28px;
  font-size: 12px;
}
.btn.seg:hover {
  background: var(--bg);
  box-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.pill {
  padding: 2px 10px;
  border-radius: 99px;
  background: var(--accent2);
  border: 1px solid rgba(56, 139, 253, 0.3);
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}
.pill.small {
  padding: 1px 8px;
  font-size: 11px;
}
.pill-func {
  color: var(--accent);
  background: var(--accent2);
}
.pill-block {
  color: var(--good);
  background: rgba(63, 185, 80, 0.15);
  border-color: rgba(63, 185, 80, 0.3);
}

.group {
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  box-shadow: var(--shadow2);
}

.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}

.group-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.group-title {
  font-weight: 600;
  font-size: 14px;
}

.gkey {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  background: var(--panel2);
  padding: 2px 6px;
  border-radius: 4px;
}

.chev {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--muted);
  padding: 0;
}
.chev:hover {
  color: var(--text);
  border-color: var(--border2);
}

.items {
  padding: 16px;
}

.item-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.item-pair:last-child {
  margin-bottom: 0;
}

@media (max-width: 1000px) {
  .item-pair {
    grid-template-columns: 1fr;
  }
}

.item {
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.item-head {
  padding: 8px 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}

.item-file {
  padding: 6px 12px;
  background: var(--panel2);
  border-bottom: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.codebox {
  margin: 0;
  padding: 12px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  background: var(--bg);
  flex: 1;
}

.empty {
  padding: 60px 0;
  display: flex;
  justify-content: center;
}
.empty-card {
  text-align: center;
  padding: 40px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  max-width: 500px;
}
.empty-icon {
  color: var(--good);
  margin-bottom: 16px;
  display: flex;
  justify-content: center;
}

.footer {
  margin-top: 60px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  border-top: 1px solid var(--border);
  padding-top: 24px;
}

${pyg_dark}
${pyg_light}
</style>
</head>

<body>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <h1>${title}</h1>
      <div class="sub">v${version}</div>
    </div>
    <div class="top-actions">
      <button class="btn" type="button" id="theme-toggle" title="Toggle theme">${icon_theme} Theme</button>
    </div>
  </div>
</div>

<div class="container">
${empty_state_html}

${func_section}
${block_section}

<div class="footer">Generated by CodeClone v${version}</div>
</div>

<script>
(() => {
  const htmlEl = document.documentElement;
  const btnTheme = document.getElementById("theme-toggle");

  const stored = localStorage.getItem("codeclone_theme");
  if (stored === "light" || stored === "dark") {
    htmlEl.setAttribute("data-theme", stored);
  }

  btnTheme?.addEventListener("click", () => {
    const cur = htmlEl.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    htmlEl.setAttribute("data-theme", next);
    localStorage.setItem("codeclone_theme", next);
  });

  // Toggle group visibility via header click
  document.querySelectorAll(".group-head").forEach((head) => {
    head.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      const btn = head.querySelector("[data-toggle-group]");
      if (btn) btn.click();
    });
  });

  document.querySelectorAll("[data-toggle-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-toggle-group");
      const body = document.getElementById("group-body-" + id);
      if (!body) return;

      const isHidden = body.style.display === "none";
      body.style.display = isHidden ? "" : "none";
      btn.style.transform = isHidden ? "rotate(0deg)" : "rotate(-90deg)";
    });
  });

  function initSection(sectionId) {
    const section = document.querySelector(`section[data-section='$${sectionId}']`);
    if (!section) return;

    const groups = Array.from(section.querySelectorAll(`.group[data-group='$${sectionId}']`));
    const searchInput = document.getElementById(`search-$${sectionId}`);
    const btnPrev = section.querySelector(`[data-prev='$${sectionId}']`);
    const btnNext = section.querySelector(`[data-next='$${sectionId}']`);
    const meta = section.querySelector(`[data-page-meta='$${sectionId}']`);
    const selPageSize = section.querySelector(`[data-pagesize='$${sectionId}']`);
    const btnClear = section.querySelector(`[data-clear='$${sectionId}']`);
    const btnCollapseAll = section.querySelector(`[data-collapse-all='$${sectionId}']`);
    const btnExpandAll = section.querySelector(`[data-expand-all='$${sectionId}']`);
    const pill = section.querySelector(`[data-count-pill='$${sectionId}']`);

    const state = {
      q: "",
      page: 1,
      pageSize: parseInt(selPageSize?.value || "10", 10),
      filtered: groups
    };

    function setGroupVisible(el, yes) {
      el.style.display = yes ? "" : "none";
    }

    function render() {
      const total = state.filtered.length;
      const pageSize = Math.max(1, state.pageSize);
      const pages = Math.max(1, Math.ceil(total / pageSize));
      state.page = Math.min(Math.max(1, state.page), pages);

      const start = (state.page - 1) * pageSize;
      const end = Math.min(total, start + pageSize);

      groups.forEach(g => setGroupVisible(g, false));
      state.filtered.slice(start, end).forEach(g => setGroupVisible(g, true));

      if (meta) meta.textContent = `Page $${state.page} / $${pages} • $${total} groups`;
      if (pill) pill.textContent = `$${total} groups`;

      if (btnPrev) btnPrev.disabled = state.page <= 1;
      if (btnNext) btnNext.disabled = state.page >= pages;
    }

    function applyFilter() {
      const q = (state.q || "").trim().toLowerCase();
      if (!q) {
        state.filtered = groups;
      } else {
        state.filtered = groups.filter(g => {
          const blob = g.getAttribute("data-search") || "";
          return blob.indexOf(q) !== -1;
        });
      }
      state.page = 1;
      render();
    }

    searchInput?.addEventListener("input", (e) => {
      state.q = e.target.value || "";
      applyFilter();
    });

    btnClear?.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      state.q = "";
      applyFilter();
    });

    selPageSize?.addEventListener("change", () => {
      state.pageSize = parseInt(selPageSize.value || "10", 10);
      state.page = 1;
      render();
    });

    btnPrev?.addEventListener("click", () => {
      state.page -= 1;
      render();
    });

    btnNext?.addEventListener("click", () => {
      state.page += 1;
      render();
    });

    btnCollapseAll?.addEventListener("click", () => {
      section.querySelectorAll(".items").forEach(b => b.style.display = "none");
      section.querySelectorAll("[data-toggle-group]").forEach(c => c.style.transform = "rotate(-90deg)");
    });

    btnExpandAll?.addEventListener("click", () => {
      section.querySelectorAll(".items").forEach(b => b.style.display = "");
      section.querySelectorAll("[data-toggle-group]").forEach(c => c.style.transform = "rotate(0deg)");
    });

    render();
  }

  initSection("functions");
  initSection("blocks");
})();
</script>
</body>
</html>
""")


def build_html_report(
    *,
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    title: str = "CodeClone Report",
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    file_cache = _FileCache()

    func_sorted = sorted(func_groups.items(), key=lambda kv: _group_sort_key(kv[1]))
    block_sorted = sorted(block_groups.items(), key=lambda kv: _group_sort_key(kv[1]))

    has_any = bool(func_sorted) or bool(block_sorted)

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
    ICON_SEARCH = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>'
    ICON_X = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'
    ICON_CHEV_DOWN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>'
    # ICON_CHEV_RIGHT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>'
    ICON_THEME = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
    ICON_CHECK = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
    ICON_PREV = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>'
    ICON_NEXT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>'

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
            f'<span class="pill {pill_cls}" data-count-pill="{section_id}">{len(groups)} groups</span></h2>',
            f"""
<div class="section-toolbar" role="toolbar" aria-label="{_escape(section_title)} controls">
  <div class="toolbar-left">
    <div class="search-wrap">
      <span class="search-ico">{ICON_SEARCH}</span>
      <input class="search" id="search-{section_id}" placeholder="Search..." autocomplete="off" />
      <button class="btn ghost" type="button" data-clear="{section_id}" title="Clear search">{ICON_X}</button>
    </div>
    <div class="segmented">
      <button class="btn seg" type="button" data-collapse-all="{section_id}">Collapse</button>
      <button class="btn seg" type="button" data-expand-all="{section_id}">Expand</button>
    </div>
  </div>

  <div class="toolbar-right">
    <div class="pager">
      <button class="btn" type="button" data-prev="{section_id}">{ICON_PREV}</button>
      <span class="page-meta" data-page-meta="{section_id}">Page 1</span>
      <button class="btn" type="button" data-next="{section_id}">{ICON_NEXT}</button>
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
                f'<div class="group" data-group="{section_id}" data-search="{search_blob_escaped}">'
            )

            out.append(
                f'<div class="group-head">'
                f'<div class="group-left">'
                f'<button class="chev" type="button" aria-label="Toggle group" data-toggle-group="{section_id}-{idx}">{ICON_CHEV_DOWN}</button>'
                f'<div class="group-title">Group #{idx}</div>'
                f'<span class="pill small {pill_cls}">{len(items)} items</span>'
                f"</div>"
                f'<div class="group-right">'
                f'<code class="gkey">{_escape(gkey)}</code>'
                f"</div>"
                f"</div>"
            )

            out.append(f'<div class="items" id="group-body-{section_id}-{idx}">')

            for a, b in pairwise(items):
                out.append('<div class="item-pair">')

                for item in (a, b):
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
    <div class="empty-icon">{ICON_CHECK}</div>
    <h2>No code clones detected</h2>
    <p>No structural or block-level duplication was found above configured thresholds.</p>
    <p class="muted">This usually indicates healthy abstraction boundaries.</p>
  </div>
</div>
"""

    func_section = render_section("functions", "Function clones", func_sorted, "pill-func")
    block_section = render_section("blocks", "Block clones", block_sorted, "pill-block")

    return REPORT_TEMPLATE.substitute(
        title=_escape(title),
        version=__version__,
        pyg_dark=pyg_dark,
        pyg_light=pyg_light,
        empty_state_html=empty_state_html,
        func_section=func_section,
        block_section=block_section,
        icon_theme=ICON_THEME,
    )
