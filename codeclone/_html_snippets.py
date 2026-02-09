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
from typing import NamedTuple, cast

from .errors import FileProcessingError


def pairwise(iterable: Iterable[object]) -> Iterable[tuple[object, object]]:
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b, strict=False)


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
        if "{" in line:
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

    try:
        lines = file_cache.get_lines_range(filepath, s, e)
    except FileProcessingError:
        missing = (
            '<div class="codebox"><pre><code>'
            '<div class="line">Source file unavailable</div>'
            "</code></pre></div>"
        )
        return _Snippet(
            filepath=filepath,
            start_line=start_line,
            end_line=end_line,
            code_html=missing,
        )

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
            rendered.append(
                f'<div class="{cls}">{html.escape(text, quote=False)}</div>'
            )
        body = "\n".join(rendered)
    else:
        body = highlighted

    return _Snippet(
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        code_html=f'<div class="codebox"><pre><code>{body}</code></pre></div>',
    )
