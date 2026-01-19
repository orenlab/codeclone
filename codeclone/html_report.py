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
        if stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("*/"):
            out_lines.append(line)
            continue
        # Selector lines usually end with `{`
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
      <span class="search-ico">⌕</span>
      <input class="search" id="search-{section_id}" placeholder="Search by qualname / path / fingerprint…" autocomplete="off" />
      <button class="btn ghost" type="button" data-clear="{section_id}" title="Clear search">×</button>
    </div>
    <div class="segmented">
      <button class="btn seg" type="button" data-collapse-all="{section_id}">Collapse</button>
      <button class="btn seg" type="button" data-expand-all="{section_id}">Expand</button>
    </div>
  </div>

  <div class="toolbar-right">
    <div class="pager">
      <button class="btn" type="button" data-prev="{section_id}">‹</button>
      <span class="page-meta" data-page-meta="{section_id}">Page 1</span>
      <button class="btn" type="button" data-next="{section_id}">›</button>
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
            # Create search blob for group:
            # - gkey (fingerprint)
            # - all qualnames + filepaths
            # This is used by JS filtering (no heavy DOM scans on each keystroke).
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
                f'<button class="chev" type="button" aria-label="Toggle group" data-toggle-group="{section_id}-{idx}">▾</button>'
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
                        f'{_escape(item["filepath"])}:'
                        f'{item["start_line"]}-{item["end_line"]}'
                        f'</div>'
                        f'{snippet.code_html}'
                        '</div>'
                    )

                out.append("</div>")  # item-pair

            out.append("</div>")  # items
            out.append("</div>")  # group

        out.append("</div>")  # section-body
        out.append("</section>")
        return "\n".join(out)

    # ============================
    # HTML
    # ============================

    empty_state_html = ""
    if not has_any:
        empty_state_html = """
<div class="empty">
  <div class="empty-card">
    <div class="empty-icon">✓</div>
    <h2>No code clones detected</h2>
    <p>No structural or block-level duplication was found above configured thresholds.</p>
    <p class="muted">This usually indicates healthy abstraction boundaries.</p>
  </div>
</div>
"""

    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>

<style>
/* ============================
   Pro UI/UX 2025 (static HTML)
   ============================ */

:root {{
  --bg: #0b0f14;
  --panel: rgba(255,255,255,0.04);
  --panel2: rgba(255,255,255,0.06);
  --text: rgba(255,255,255,0.92);
  --muted: rgba(255,255,255,0.62);
  --border: rgba(255,255,255,0.10);
  --border2: rgba(255,255,255,0.14);
  --accent: #6aa6ff;
  --accent2: rgba(106,166,255,0.18);
  --good: #7cffa0;
  --shadow: 0 18px 60px rgba(0,0,0,.55);
  --shadow2: 0 10px 26px rgba(0,0,0,.45);
  --radius: 14px;
  --radius2: 18px;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}}

html[data-theme="light"] {{
  --bg: #f6f8fb;
  --panel: rgba(0,0,0,0.03);
  --panel2: rgba(0,0,0,0.05);
  --text: rgba(0,0,0,0.88);
  --muted: rgba(0,0,0,0.55);
  --border: rgba(0,0,0,0.10);
  --border2: rgba(0,0,0,0.14);
  --accent: #1f6feb;
  --accent2: rgba(31,111,235,0.14);
  --good: #1f883d;
  --shadow: 0 18px 60px rgba(0,0,0,.12);
  --shadow2: 0 10px 26px rgba(0,0,0,.10);
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background: radial-gradient(1200px 800px at 20% -10%, rgba(106,166,255,.18), transparent 45%),
              radial-gradient(900px 600px at 80% 0%, rgba(124,255,160,.10), transparent 35%),
              var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.55;
}}

.container {{
  max-width: 1600px;
  margin: 0 auto;
  padding: 26px 22px 110px;
}}

.topbar {{
  position: sticky;
  top: 0;
  z-index: 50;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  background: linear-gradient(to bottom, rgba(0,0,0,.35), rgba(0,0,0,0));
  border-bottom: 1px solid var(--border);
  padding: 14px 0 12px;
}}

.topbar-inner {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}}

.brand {{
  display: flex;
  flex-direction: column;
  gap: 3px;
}}

.brand h1 {{
  margin: 0;
  font-size: 22px;
  letter-spacing: 0.2px;
}}

.brand .sub {{
  color: var(--muted);
  font-size: 12.5px;
}}

.top-actions {{
  display: flex;
  align-items: center;
  gap: 10px;
}}

.btn {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  font-size: 12.5px;
  box-shadow: var(--shadow2);
}}

.btn:hover {{
  border-color: var(--border2);
  background: var(--panel2);
}}

.btn:active {{
  transform: translateY(1px);
}}

.btn.ghost {{
  background: transparent;
  box-shadow: none;
}}

.select {{
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  font-weight: 600;
  font-size: 12.5px;
}}

.section {{
  margin-top: 22px;
}}

.section-head {{
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 18px;
}}

.section-head h2 {{
  margin: 0;
  font-size: 16px;
  letter-spacing: 0.2px;
}}

.section-toolbar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}}

.toolbar-left, .toolbar-right {{
  display: flex;
  align-items: center;
  gap: 10px;
}}

.search-wrap {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow2);
  min-width: 320px;
}}

.search-ico {{
  opacity: .72;
  font-weight: 800;
}}

.search {{
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}}

.search::placeholder {{
  color: var(--muted);
}}

.segmented {{
  display: inline-flex;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border);
}}

.btn.seg {{
  border: none;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}}

.pager {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
}}

.page-meta {{
  color: var(--muted);
  font-size: 12.5px;
  min-width: 120px;
  text-align: center;
}}

.pill {{
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent2);
  border: 1px solid rgba(106,166,255,0.25);
  font-size: 12px;
  font-weight: 800;
  color: var(--text);
}}

.pill.small {{
  padding: 3px 8px;
  font-size: 11px;
}}

.pill-func {{
  background: rgba(106,166,255,0.14);
  border-color: rgba(106,166,255,0.25);
}}

.pill-block {{
  background: rgba(124,255,160,0.10);
  border-color: rgba(124,255,160,0.22);
}}

.section-body {{
  margin-top: 12px;
}}

.group {{
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius2);
  background: var(--panel);
  box-shadow: var(--shadow);
  overflow: hidden;
}}

.group-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}}

.group-left {{
  display: flex;
  align-items: center;
  gap: 10px;
}}

.group-title {{
  font-weight: 900;
  font-size: 13px;
}}

.group-right {{
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 60%;
}}

.gkey {{
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.chev {{
  width: 30px;
  height: 30px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel2);
  color: var(--text);
  cursor: pointer;
  font-weight: 900;
}}

.items {{
  padding: 14px;
}}

.item-pair {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}}

@media (max-width: 1100px) {{
  .item-pair {{
    grid-template-columns: 1fr;
  }}
  .search-wrap {{
    min-width: 260px;
  }}
}}

.item {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: rgba(0,0,0,0.10);
}}

html[data-theme="light"] .item {{
  background: rgba(255,255,255,0.60);
}}

.item-head {{
  padding: 10px 12px;
  font-weight: 900;
  font-size: 12.8px;
  border-bottom: 1px solid var(--border);
}}

.item-file {{
  padding: 6px 12px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}}

.codebox {{
  margin: 0;
  padding: 12px;
  font-family: var(--mono);
  font-size: 12.5px;
  overflow: auto;
  background: rgba(0,0,0,0.18);
}}

html[data-theme="light"] .codebox {{
  background: rgba(0,0,0,0.03);
}}

.line {{
  white-space: pre;
}}

.hitline {{
  white-space: pre;
  background: rgba(255, 184, 107, .18);
}}

.empty {{
  margin-top: 34px;
  display: flex;
  justify-content: center;
}}

.empty-card {{
  max-width: 640px;
  border-radius: 22px;
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 26px 26px;
  text-align: center;
}}

.empty-icon {{
  font-size: 52px;
  color: var(--good);
  font-weight: 900;
  margin-bottom: 8px;
}}

.footer {{
  margin-top: 40px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}}

.muted {{
  color: var(--muted);
}}

/* ============================
   Pygments CSS (SCOPED)
   IMPORTANT: without this, `nowrap=True` output won't be colored.
   ============================ */
{pyg_dark}
{pyg_light}
</style>
</head>

<body>
<div class="topbar">
  <div class="container">
    <div class="topbar-inner">
      <div class="brand">
        <h1>{_escape(title)}</h1>
        <div class="sub">AST + CFG clone detection • CodeClone v{__version__}</div>
      </div>

      <div class="top-actions">
        <button class="btn" type="button" id="theme-toggle" title="Toggle theme">🌓 Theme</button>
      </div>
    </div>
  </div>
</div>

<div class="container">
{empty_state_html}

{render_section("functions", "Function clones (Type-2)", func_sorted, "pill-func")}
{render_section("blocks", "Block clones (Type-3-lite)", block_sorted, "pill-block")}

<div class="footer">Generated by CodeClone v{__version__}</div>
</div>

<script>
(() => {{
  // ----------------------------
  // Theme toggle
  // ----------------------------
  const htmlEl = document.documentElement;
  const btnTheme = document.getElementById("theme-toggle");

  const stored = localStorage.getItem("codeclone_theme");
  if (stored === "light" || stored === "dark") {{
    htmlEl.setAttribute("data-theme", stored);
  }}

  btnTheme?.addEventListener("click", () => {{
    const cur = htmlEl.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    htmlEl.setAttribute("data-theme", next);
    localStorage.setItem("codeclone_theme", next);
  }});

  // ----------------------------
  // Group collapse toggles
  // ----------------------------
  document.querySelectorAll("[data-toggle-group]").forEach((btn) => {{
    btn.addEventListener("click", () => {{
      const id = btn.getAttribute("data-toggle-group");
      const body = document.getElementById("group-body-" + id);
      if (!body) return;

      const isHidden = body.style.display === "none";
      body.style.display = isHidden ? "" : "none";
      btn.textContent = isHidden ? "▾" : "▸";
    }});
  }});

  // ----------------------------
  // Search + Pagination ("soft virtualization")
  // ----------------------------
  function initSection(sectionId) {{
    const section = document.querySelector(`section[data-section='${{sectionId}}']`);
    if (!section) return;

    const groups = Array.from(section.querySelectorAll(`.group[data-group='${{sectionId}}']`));
    const searchInput = document.getElementById(`search-${{sectionId}}`);

    const btnPrev = section.querySelector(`[data-prev='${{sectionId}}']`);
    const btnNext = section.querySelector(`[data-next='${{sectionId}}']`);
    const meta = section.querySelector(`[data-page-meta='${{sectionId}}']`);
    const selPageSize = section.querySelector(`[data-pagesize='${{sectionId}}']`);

    const btnClear = section.querySelector(`[data-clear='${{sectionId}}']`);
    const btnCollapseAll = section.querySelector(`[data-collapse-all='${{sectionId}}']`);
    const btnExpandAll = section.querySelector(`[data-expand-all='${{sectionId}}']`);
    const pill = section.querySelector(`[data-count-pill='${{sectionId}}']`);

    const state = {{
      q: "",
      page: 1,
      pageSize: parseInt(selPageSize?.value || "10", 10),
      filtered: groups
    }};

    function setGroupVisible(el, yes) {{
      el.style.display = yes ? "" : "none";
    }}

    function applyFilter() {{
      const q = (state.q || "").trim().toLowerCase();
      if (!q) {{
        state.filtered = groups;
      }} else {{
        state.filtered = groups.filter(g => {{
          const blob = g.getAttribute("data-search") || "";
          return blob.indexOf(q) !== -1;
        }});
      }}
      state.page = 1;
      render();
    }}

    function render() {{
      const total = state.filtered.length;
      const pageSize = Math.max(1, state.pageSize);
      const pages = Math.max(1, Math.ceil(total / pageSize));
      state.page = Math.min(Math.max(1, state.page), pages);

      const start = (state.page - 1) * pageSize;
      const end = Math.min(total, start + pageSize);

      // hide all (this is the "virtualization": only show the slice)
      groups.forEach(g => setGroupVisible(g, false));
      state.filtered.slice(start, end).forEach(g => setGroupVisible(g, true));

      if (meta) {{
        meta.textContent = `Page ${{state.page}} / ${{pages}} • ${{total}} groups`;
      }}
      if (pill) {{
        pill.textContent = `${{total}} groups`;
      }}

      if (btnPrev) btnPrev.disabled = state.page <= 1;
      if (btnNext) btnNext.disabled = state.page >= pages;
    }}

    // Wiring
    searchInput?.addEventListener("input", (e) => {{
      state.q = e.target.value || "";
      applyFilter();
    }});

    btnClear?.addEventListener("click", () => {{
      if (searchInput) searchInput.value = "";
      state.q = "";
      applyFilter();
    }});

    selPageSize?.addEventListener("change", () => {{
      state.pageSize = parseInt(selPageSize.value || "10", 10);
      state.page = 1;
      render();
    }});

    btnPrev?.addEventListener("click", () => {{
      state.page -= 1;
      render();
    }});

    btnNext?.addEventListener("click", () => {{
      state.page += 1;
      render();
    }});

    btnCollapseAll?.addEventListener("click", () => {{
      section.querySelectorAll(".items").forEach((b) => {{
        b.style.display = "none";
      }});
      section.querySelectorAll("[data-toggle-group]").forEach((c) => {{
        c.textContent = "▸";
      }});
    }});

    btnExpandAll?.addEventListener("click", () => {{
      section.querySelectorAll(".items").forEach((b) => {{
        b.style.display = "";
      }});
      section.querySelectorAll("[data-toggle-group]").forEach((c) => {{
        c.textContent = "▾";
      }});
    }});

    // Initial render
    render();
  }}

  initSection("functions");
  initSection("blocks");
}})();
</script>
</body>
</html>
"""
