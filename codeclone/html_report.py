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

    # ----------------------------
    # Section renderer
    # ----------------------------

    def render_section(
            section_id: str,
            title: str,
            groups: list[tuple[str, list[dict[str, Any]]]],
            pill_cls: str,
    ) -> str:
        if not groups:
            return ""

        out: list[str] = [
            f'<section id="{section_id}" class="section">',
            f"<h2>{_escape(title)} "
            f'<span class="pill {pill_cls}">{len(groups)} groups</span></h2>',
        ]

        for idx, (gkey, items) in enumerate(groups, start=1):
            out.append('<div class="group">')
            out.append(
                f'<div class="group-head">'
                f'<div class="group-title">Group #{idx}</div>'
                f'<div class="group-meta">'
                f'<span class="pill {pill_cls}">{len(items)} items</span>'
                f'<span class="muted">{_escape(gkey)}</span>'
                f"</div></div>"
            )

            out.append('<div class="items">')

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

            out.append("</div></div>")

        out.append("</section>")
        return "\n".join(out)

    # ============================
    # HTML
    # ============================

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>

<style>
:root {{
  --bg: #0e1117;
  --panel: #161b22;
  --text: #e6edf3;
  --muted: #8b949e;
  --border: #30363d;
  --accent: #58a6ff;
  --good: #3fb950;
  --shadow: 0 12px 32px rgba(0,0,0,.4);
  --radius: 12px;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
}}

.container {{
  max-width: 1600px;
  margin: auto;
  padding: 32px 24px 96px;
}}

.header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}}

.section {{ margin-top: 32px; }}

.pill {{
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(88,166,255,.15);
  font-size: 12px;
  font-weight: 600;
}}

.group {{
  margin-top: 20px;
  background: var(--panel);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}}

.group-head {{
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
}}

.items {{ padding: 16px; }}

.item-pair {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}}

.item {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}}

.item-head {{
  padding: 10px 14px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}}

.item-file {{
  padding: 6px 14px;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}}

.codebox {{
  margin: 0;
  padding: 14px;
  font-family: var(--mono);
  font-size: 13px;
  overflow: auto;
  background: #0d1117;
}}

.hitline {{ background: rgba(255,184,107,.18); }}

.footer {{
  margin-top: 48px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}}
</style>
</head>

<body>
<div class="container">

<div class="header">
  <div>
    <h1>{_escape(title)}</h1>
    <div class="muted">
      AST + CFG clone detection • CodeClone v{__version__}
    </div>
  </div>
</div>

{render_section("functions", "Function clones (Type-2)", func_sorted, "pill")}
{render_section("blocks", "Block clones (Type-3-lite)", block_sorted, "pill")}

<div class="footer">
  Generated by CodeClone v{__version__}
</div>

</div>
</body>
</html>
"""
