# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from ... import __version__
from ... import ui_messages as ui
from ...report.gates import reasons as gate_reasons
from . import state as cli_state

if TYPE_CHECKING:
    from rich.console import Console as RichConsole
    from rich.progress import BarColumn as RichBarColumn
    from rich.progress import Progress as RichProgress
    from rich.progress import SpinnerColumn as RichSpinnerColumn
    from rich.progress import TextColumn as RichTextColumn
    from rich.progress import TimeElapsedColumn as RichTimeElapsedColumn
    from rich.rule import Rule as RichRule
    from rich.theme import Theme as RichTheme

_RICH_THEME_STYLES: dict[str, str] = {
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "dim": "dim",
}
_RICH_MARKUP_TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_ .#:-]*]")


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


class PlainConsole:
    """Lightweight console for quiet/no-progress mode."""

    @staticmethod
    def print(
        *objects: object,
        sep: str = " ",
        end: str = "\n",
        markup: bool = True,
        **_: object,
    ) -> None:
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


def make_plain_console() -> PlainConsole:
    return PlainConsole()


def _render_banner(
    *,
    console: _PrinterLike,
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


def _console() -> _PrinterLike:
    return cast("_PrinterLike", cli_state.get_console())


def _rich_progress_symbols() -> tuple[type[object], ...]:
    return cast("tuple[type[object], ...]", rich_progress_symbols())


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
    args: object,
) -> None:
    gate_reasons.print_gating_failure_block(
        console=_console(),
        code=code,
        entries=list(entries),
        args=cast("Any", args),
    )


def build_html_report(*args: object, **kwargs: object) -> str:
    from ...report.html import build_html_report as _build_html_report

    html_builder: Callable[..., str] = _build_html_report
    return html_builder(*args, **kwargs)


def _print_verbose_clone_hashes(
    console: _PrinterLike,
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
