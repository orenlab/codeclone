from __future__ import annotations

import html
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Iterable, TYPE_CHECKING

# ============================
# Optional pygments typing
# ============================

if TYPE_CHECKING:
    pass


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
                snippet_a = _render_code_block(
                    filepath=a["filepath"],
                    start_line=int(a["start_line"]),
                    end_line=int(a["end_line"]),
                    file_cache=file_cache,
                    context=context_lines,
                    max_lines=max_snippet_lines,
                )
                snippet_b = _render_code_block(
                    filepath=b["filepath"],
                    start_line=int(b["start_line"]),
                    end_line=int(b["end_line"]),
                    file_cache=file_cache,
                    context=context_lines,
                    max_lines=max_snippet_lines,
                )

                out.append('<div class="item-pair">')

                for item, snippet in ((a, snippet_a), (b, snippet_b)):
                    out.append('<div class="item">')
                    out.append(
                        f'<div class="item-head">{_escape(item["qualname"])}</div>'
                        f'<div class="item-file">'
                        f"{_escape(item['filepath'])}:"
                        f"{item['start_line']}-{item['end_line']}"
                        f"</div>"
                    )
                    out.append(f'<div class="snippet">{snippet.code_html}</div>')
                    out.append("</div>")

                out.append("</div>")

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
  --bg: #fff;
  --text: #111;
  --muted: #666;
  --border: #ddd;
  --accent: #007bff;
  --good: #28a745;
  --shadow: 0 4px 6px rgba(0,0,0,.1);
  --radius: 8px;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}}
html[data-theme='dark'] {{
  --bg: #0b0f1a;
  --text: #e7ecff;
  --muted: #a9b3d6;
  --border: #223055;
  --accent: #6aa6ff;
  --good: #7cffa0;
  --shadow: 0 14px 40px rgba(0,0,0,.35);
}}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.6;
}}
.container {{
  max-width: 1400px;
  margin: auto;
  padding: 28px 18px 80px;
}}
.header {{
  padding: 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.section {{ margin-top: 28px; }}
.pill {{
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
}}
.pill-func {{ background: rgba(106, 166, 255, .16); }}
.pill-block {{ background: rgba(124, 255, 160, .14); }}
.group {{
  margin-top: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  box-shadow: var(--shadow);
  overflow: hidden;
}}
.group-head {{
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.group-title {{ font-weight: 600; }}
.items {{ padding: 12px; }}
.item-pair {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}}
.item {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}}
.item-head, .item-file {{
  padding: 8px 12px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}}
.item-file {{
  font-family: var(--mono);
  color: var(--muted);
  font-size: 12px;
}}
.codebox {{
  padding: 12px;
  margin: 0;
  font-family: var(--mono);
  font-size: 12.5px;
  overflow: auto;
  background: var(--bg);
}}
.hitline {{ background: rgba(255, 184, 107, .18); }}
.clean {{
  margin-top: 60px;
  display: flex;
  justify-content: center;
}}
.clean-card {{
  max-width: 520px;
  padding: 32px;
  text-align: center;
  border-radius: 20px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}}
.clean-icon {{
  font-size: 48px;
  color: var(--good);
  margin-bottom: 12px;
}}
.footer {{
  margin-top: 40px;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}}
#theme-toggle {{
  cursor: pointer;
  font-size: 1.5rem;
}}
</style>
</head>

<body>
<div class="container">

<div class="header">
  <div>
    <h1>{_escape(title)}</h1>
    <div class="muted">AST-normalized clone detection • function + block analysis</div>
  </div>
  <div id="theme-toggle">🌓</div>
</div>

{
        "".join(
            [
                '''
<div class="clean">
  <div class="clean-card">
    <div class="clean-icon">✓</div>
    <h2>No code clones detected</h2>
    <p>No structural or block-level duplication was found above configured thresholds.</p>
    <p class="muted">This usually indicates healthy abstraction boundaries.</p>
  </div>
</div>
'''
                if not has_any
                else ""
            ]
        )
    }

{render_section("functions", "Function clones (Type-2)", func_sorted, "pill-func")}
{render_section("blocks", "Block clones (Type-3-lite)", block_sorted, "pill-block")}

<div class="footer">Generated by CodeClone.</div>
</div>

<script>
  const themeToggle = document.getElementById('theme-toggle');
  const htmlEl = document.documentElement;

  const currentTheme = localStorage.getItem('theme') || 'light';
  htmlEl.setAttribute('data-theme', currentTheme);

  themeToggle.addEventListener('click', function() {{
    const newTheme = htmlEl.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    htmlEl.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
  }});
</script>
</body>
</html>
"""
