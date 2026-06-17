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
from ...report.gates import reasons as gate_reasons
from . import state as cli_state
from .types import CLIArgsLike, PrinterLike, StatusConsole, require_status_console

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

_RICH_THEME_STYLES: dict[str, str] = {
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "dim": "dim",
}
_RICH_MARKUP_TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_ .#:-]*]")


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
            text = _RICH_MARKUP_TAG_RE.sub("", text)
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


def make_console(*, no_color: bool, width: int) -> RichConsole:
    console_cls, theme_cls, _ = rich_console_symbols()
    return console_cls(
        theme=theme_cls(_RICH_THEME_STYLES),
        no_color=no_color,
        width=width,
    )


def supports_rich_console(console: PrinterLike) -> bool:
    return console.__class__.__module__.startswith("rich.")


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


def make_query_console(*, no_color: bool | None = None) -> PrinterLike:
    resolved_no_color = (
        bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()
        if no_color is None
        else no_color
    )
    return cast(
        PrinterLike,
        make_console(no_color=resolved_no_color, width=ui.CLI_AUDIT_MAX_WIDTH),
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
            title=f"Analyze: {project_name}" if project_name else "Analyze",
            style="dim",
            characters="\u2500",
        )
    )
    if root_display is not None:
        console.print(f"  [dim]Root:[/dim] [dim]{root_display}[/dim]")


def _console() -> StatusConsole:
    return require_status_console(cli_state.get_console())


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


def _print_gating_failure_block(
    *,
    code: str,
    entries: Sequence[tuple[str, object]],
    args: CLIArgsLike,
) -> None:
    gate_reasons.print_gating_failure_block(
        console=_console(),
        code=code,
        entries=list(entries),
        args=args,
    )


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


def print_banner(*, root: Path | None = None) -> None:
    _render_banner(
        console=_console(),
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
