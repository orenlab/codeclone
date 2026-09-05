# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import re
import sys
import types
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ... import __version__
from ... import ui_messages as ui
from ...contracts import ExitCode
from ...report.gates import reasons as gate_reasons
from ...ui_messages.styling import _L, INDENT_UNIT, RICH_THEME_STYLES, strip_markup
from .types import CLIArgsLike, PrinterLike

if TYPE_CHECKING:
    from rich.console import Console as RichConsole
    from rich.panel import Panel as RichPanel
    from rich.progress import BarColumn as RichBarColumn
    from rich.progress import Progress as RichProgress
    from rich.progress import SpinnerColumn as RichSpinnerColumn
    from rich.progress import TextColumn as RichTextColumn
    from rich.progress import TimeElapsedColumn as RichTimeElapsedColumn
    from rich.rule import Rule as RichRule
    from rich.table import Table as RichTable
    from rich.text import Text as RichText
    from rich.theme import Theme as RichTheme


#: The narrowest column a hanging continuation may be wrapped into. Below
#: this the indentation itself would eat the line, so the line is left to
#: the terminal instead of being folded into a sliver.
_MIN_HANGING_COLUMN = 24

#: The value column of the design grid: one indent unit plus the label
#: field. A row whose label sits in that field hangs its continuation under
#: the value, not under the label.
_VALUE_COLUMN = INDENT_UNIT + _L

#: List items: the continuation of a wrapped item sits under its text.
_BULLETS = frozenset({"- ", "• "})

#: A design-grid label row: the indent, a capitalised one- or two-word
#: label, then padding up to the value column. Glyphed lines, detail lines
#: and prose never match, so they hang under their own indentation.
_LABEL_ROW_RE = re.compile(
    r"^ {" + str(INDENT_UNIT) + r"}[A-Z][A-Za-z]*(?: [A-Za-z]+)? +(?=\S)"
)


class PlainConsole:
    """Lightweight console for quiet/no-progress mode."""

    def print(
        self,
        *objects: object,
        **kwargs: object,
    ) -> None:
        sep_obj = kwargs.get("sep", " ")
        end_obj = kwargs.get("end", "\n")
        markup_obj = kwargs.get("markup", True)
        sep = sep_obj if isinstance(sep_obj, str) else " "
        end = end_obj if isinstance(end_obj, str) else "\n"
        markup = markup_obj if isinstance(markup_obj, bool) else True
        text = sep.join(str(obj) for obj in objects)
        if markup:
            text = strip_markup(text)
        print(text, end=end)

    @staticmethod
    def status(*_: object, **__: object) -> AbstractContextManager[None]:
        return nullcontext()


@lru_cache(maxsize=1)
def rich_console_symbols() -> tuple[
    type[RichConsole],
    type[RichTheme],
    type[RichRule],
]:
    from rich.console import Console as _RichConsole
    from rich.rule import Rule as _RichRule
    from rich.theme import Theme as _RichTheme

    return _RichConsole, _RichTheme, _RichRule


@lru_cache(maxsize=1)
def rich_progress_symbols() -> tuple[
    type[RichProgress],
    type[RichSpinnerColumn],
    type[RichTextColumn],
    type[RichBarColumn],
    type[RichTimeElapsedColumn],
]:
    import rich.progress as _rich_progress

    return (
        _rich_progress.Progress,
        _rich_progress.SpinnerColumn,
        _rich_progress.TextColumn,
        _rich_progress.BarColumn,
        _rich_progress.TimeElapsedColumn,
    )


@lru_cache(maxsize=1)
def grid_console_class() -> type[RichConsole]:
    """The CLI console: a Rich console whose wrapped text keeps its column.

    Every line of a printed string owns the column its indentation opens. When
    the line is longer than the console, the continuation lines are indented
    to that same column instead of falling back to column 0 -- a path under
    ``Root`` stays under ``Root``, a detail under a warning glyph stays under
    the glyph. Renderables (rules, tables, progress) and prints that ask for
    ``soft_wrap`` / ``no_wrap`` / an explicit ``width`` pass through to Rich
    untouched.

    Built lazily so quiet mode never pays for the Rich import.
    """

    from rich.console import Console as _RichConsole
    from rich.console import JustifyMethod, OverflowMethod
    from rich.style import Style
    from rich.text import Text

    class GridConsole(_RichConsole):
        def _hang(self, text: Text) -> Text:
            width = self.width
            lines: list[Text] = []
            for line in text.split("\n", allow_blank=True):
                plain = line.plain
                indent = len(plain) - len(plain.lstrip(" "))
                label_row = _LABEL_ROW_RE.match(plain)
                if label_row is not None and label_row.end() == _VALUE_COLUMN:
                    indent = _VALUE_COLUMN
                elif plain[indent : indent + 2] in _BULLETS:
                    # A list item hangs under its text, not under its bullet.
                    indent += 2
                available = width - indent
                if line.cell_len <= width or available < _MIN_HANGING_COLUMN:
                    lines.append(line)
                    continue
                head = line[:indent]
                body = line[indent:]
                parts = body.wrap(self, available, overflow="fold")
                for index, part in enumerate(parts):
                    part.rstrip()
                    prefix = head if index == 0 else Text(" " * indent)
                    lines.append(prefix + part)
            return Text("\n").join(lines)

        def print(
            self,
            *objects: object,
            sep: str = " ",
            end: str = "\n",
            style: str | Style | None = None,
            justify: JustifyMethod | None = None,
            overflow: OverflowMethod | None = None,
            no_wrap: bool | None = None,
            emoji: bool | None = None,
            markup: bool | None = None,
            highlight: bool | None = None,
            width: int | None = None,
            height: int | None = None,
            crop: bool = True,
            soft_wrap: bool | None = None,
            new_line_start: bool = False,
        ) -> None:
            passthrough = (
                not objects
                or bool(soft_wrap)
                or bool(no_wrap)
                or width is not None
                or any(not isinstance(item, str) for item in objects)
            )
            if passthrough:
                super().print(
                    *objects,
                    sep=sep,
                    end=end,
                    style=style,
                    justify=justify,
                    overflow=overflow,
                    no_wrap=no_wrap,
                    emoji=emoji,
                    markup=markup,
                    highlight=highlight,
                    width=width,
                    height=height,
                    crop=crop,
                    soft_wrap=soft_wrap,
                    new_line_start=new_line_start,
                )
                return
            rendered = self.render_str(
                sep.join(str(item) for item in objects),
                emoji=emoji,
                markup=markup,
                highlight=highlight,
            )
            super().print(
                self._hang(rendered),
                end=end,
                style=style,
                justify=justify,
                overflow="ignore",
                no_wrap=True,
                emoji=False,
                markup=False,
                highlight=False,
                height=height,
                crop=crop,
                new_line_start=new_line_start,
            )

    return GridConsole


def make_console(*, no_color: bool, width: int) -> RichConsole:
    _, theme_cls, _ = rich_console_symbols()
    return grid_console_class()(
        theme=theme_cls(RICH_THEME_STYLES),
        no_color=no_color,
        width=width,
        # Colour states a verdict or a count role, never decoration: the
        # design map owns every colour on screen, so Rich's own number and
        # string highlighter stays off.
        highlight=False,
    )


def supports_rich_console(console: PrinterLike) -> bool:
    return any(cls.__module__.startswith("rich.") for cls in type(console).__mro__)


@lru_cache(maxsize=1)
def rich_panel_symbols() -> tuple[
    types.ModuleType,
    type[RichPanel],
    type[RichRule],
    type[RichTable],
    type[RichText],
]:
    from rich import box
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    return box, Panel, Rule, Table, Text


def make_query_console(
    *,
    no_color: bool | None = None,
    width: int = ui.CLI_AUDIT_MAX_WIDTH,
) -> PrinterLike:
    resolved_no_color = (
        bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()
        if no_color is None
        else no_color
    )
    return cast(
        PrinterLike,
        make_console(no_color=resolved_no_color, width=width),
    )


def make_plain_console() -> PlainConsole:
    return PlainConsole()


def _render_banner(
    *,
    console: PrinterLike,
    banner_title: str,
    project_name: str | None = None,
    root_display: str | None = None,
) -> None:
    _, _, rule_cls = rich_console_symbols()
    console.print(banner_title)
    console.print()
    console.print(
        rule_cls(
            title=project_name if project_name else "Analyze",
            style=ui.STYLE_META,
            characters=ui.GLYPH_RULE,
        )
    )
    if root_display is not None:
        console.print(ui.fmt_banner_root(root_display))


def _rich_progress_symbols() -> tuple[
    type[RichProgress],
    type[RichSpinnerColumn],
    type[RichTextColumn],
    type[RichBarColumn],
    type[RichTimeElapsedColumn],
]:
    progress, spinner, text, bar, elapsed = rich_progress_symbols()
    return (progress, spinner, text, bar, elapsed)


def _make_console(*, no_color: bool) -> object:
    return make_console(no_color=no_color, width=ui.CLI_LAYOUT_MAX_WIDTH)


def _make_plain_console() -> PlainConsole:
    return make_plain_console()


def _parse_metric_reason_entry(reason: str) -> tuple[str, str]:
    return gate_reasons.parse_metric_reason_entry(reason)


def _gate_row_label(key: str) -> str:
    """Spell a gate-evidence key the way the reader reads it.

    The keys are the gate layer's identifiers (``complexity_max``,
    ``new_function_clone_groups``); the row label is the same words with the
    underscores gone and a capital first letter. Total and deterministic, so a
    key this surface has never seen still reads as words.
    """

    words = key.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _print_gating_failure_block(
    *,
    console: PrinterLike,
    code: str,
    entries: Sequence[tuple[str, object]],
    args: CLIArgsLike,
) -> None:
    from ...report.messages import gates as gate_msgs

    console.print()
    console.print(
        f"  {ui.GLYPH_FAIL} {gate_msgs.GATE_FAILURE_HEADER.format(code=code)}"
        f" {ui.GLYPH_SEP} exit {int(ExitCode.GATING_FAILURE)}",
        style=ui.STYLE_VERDICT_FAIL,
        markup=False,
    )
    rows = [
        (
            _gate_row_label("policy"),
            gate_reasons.policy_context(args=args, gate_kind=code),
        )
    ]
    rows.extend((_gate_row_label(key), str(value)) for key, value in entries)
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        console.print(f"    {label:<{width}}  {value}", markup=False)


def _print_verbose_clone_hashes(
    console: PrinterLike,
    *,
    label: str,
    clone_hashes: set[str],
) -> None:
    if not clone_hashes:
        return
    console.print(f"\n    {label}:")
    for clone_hash in sorted(clone_hashes):
        console.print(f"      - {clone_hash}")


def print_banner(*, console: PrinterLike, root: Path | None = None) -> None:
    _render_banner(
        console=console,
        banner_title=ui.banner_title(__version__),
        project_name=(root.name if root is not None else None),
        root_display=(str(root) if root is not None else None),
    )


def _is_debug_enabled(
    *,
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    debug_from_flag = any(arg == "--debug" for arg in args)
    env = os.environ if environ is None else environ
    debug_from_env = env.get("CODECLONE_DEBUG") == "1"
    return debug_from_flag or debug_from_env
