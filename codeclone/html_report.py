from __future__ import annotations

import html
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from . import __version__

# ============================
# Version
# ============================
CODECLONE_VERSION = __version__


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


# ============================
# Pygments
# ============================


def _try_pygments(code: str) -> Optional[str]:
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import PythonLexer
    except Exception:
        return None

    return highlight(code, PythonLexer(), HtmlFormatter(nowrap=True))


def _pygments_css() -> str:
    try:
        from pygments.formatters import HtmlFormatter
    except Exception:
        return ""

    formatter = HtmlFormatter(style="dracula")
    return formatter.get_style_defs(".codebox code")


# ============================
# Rendering
# ============================


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
        numbered.append((hit, f"{lineno:>5} │ {line.rstrip()}"))

    raw = "\n".join(text for _, text in numbered)
    highlighted = _try_pygments(raw)

    if highlighted is None:
        body = "\n".join(
            f'<div class="{"hitline" if hit else "line"}">{html.escape(text)}</div>'
            for hit, text in numbered
        )
    else:
        body = highlighted

    return _Snippet(
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        code_html=f'<pre class="codebox"><code>{body}</code></pre>',
    )


# ============================
# HTML Report
# ============================


def _escape(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def build_html_report(
        *,
        func_groups: dict[str, list[dict[str, Any]]],
        block_groups: dict[str, list[dict[str, Any]]],
        title: str = "CodeClone Report",
        context_lines: int = 3,
        max_snippet_lines: int = 220,
) -> str:
    file_cache = _FileCache()
    pygments_css = _pygments_css()

    has_any = bool(func_groups) or bool(block_groups)

    def render(groups, section_id, title, pill_cls):
        if not groups:
            return ""

        out = [
            f'<section id="{section_id}" class="section">',
            f"<h2>{_escape(title)} <span class='pill {pill_cls}'>{len(groups)} groups</span></h2>",
        ]

        for idx, (gkey, items) in enumerate(groups.items(), start=1):
            out.append("<div class='group'>")
            out.append(
                f"<div class='group-head'>"
                f"<div class='group-title'>Group #{idx}</div>"
                f"<div class='group-meta'>"
                f"<span class='pill {pill_cls}'>{len(items)} items</span>"
                f"<span class='muted'>{_escape(gkey)}</span>"
                f"</div></div>"
            )

            out.append("<div class='items'>")
            for a, b in pairwise(items):
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
                        f"<div class='item'>"
                        f"<div class='item-head'>{_escape(item['qualname'])}</div>"
                        f"<div class='item-file'>{_escape(item['filepath'])}:{item['start_line']}-{item['end_line']}</div>"
                        f"{snippet.code_html}"
                        f"</div>"
                    )
            out.append("</div></div>")

        out.append("</section>")
        return "\n".join(out)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_escape(title)}</title>

<style>
{pygments_css}

/* UI */
body {{
  margin: 0;
  background: #0b0f1a;
  color: #e7ecff;
  font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}}

.container {{
  max-width: 1500px;
  margin: auto;
  padding: 32px;
}}

.header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}}

.codebox {{
  background: #0f1629;
  border-radius: 10px;
  padding: 12px;
  overflow: auto;
  font-size: 13px;
}}

.hitline {{
  background: rgba(255, 184, 107, .18);
}}

.footer {{
  margin-top: 60px;
  text-align: center;
  color: #8a94c7;
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
      AST + CFG clone detection • CodeClone v{CODECLONE_VERSION}
    </div>
  </div>
</div>

{"" if has_any else "<p>No code clones detected 🎉</p>"}

{render(func_groups, "functions", "Function clones (Type-2)", "pill-func")}
{render(block_groups, "blocks", "Block clones (Type-3-lite)", "pill-block")}

<div class="footer">
Generated by CodeClone v{CODECLONE_VERSION}
</div>

</div>
</body>
</html>
"""
