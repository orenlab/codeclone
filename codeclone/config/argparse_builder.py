# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from typing import NoReturn, Protocol, TypeVar, overload

from .. import ui_messages as ui
from ..contracts import ExitCode, cli_help_epilog
from ..models import OptionSpec
from .spec import ARGUMENT_GROUP_TITLES, DEFAULTS_BY_DEST, OPTIONS

_NamespaceT = TypeVar("_NamespaceT")


class _TextWriter(Protocol):
    def write(self, text: str, /) -> object: ...


def _handle_interactive_help(
    argv: tuple[str, ...],
    *,
    on_error: Callable[[str], NoReturn],
) -> None:
    """Dispatch ``--help --interactive-help``, and own the tour's interrupt.

    Leaving a tour early is how a reader ends it, not a fault, so Ctrl+C must
    not read like one.  Nothing on this path used to catch it:
    ``KeyboardInterrupt`` is a ``BaseException``, so ``main``'s ``except
    Exception`` envelope never sees it, and the interpreter printed its own
    stack over the last animation frame -- five files of CodeClone internals
    shown to somebody who had asked for help.

    The guard sits here rather than inside the tour because this is the
    boundary of the whole tour: the import, building the console, the first
    frame before the Live starts, every sleep inside a step, and the gap
    between steps are all under it.  A guard around the sleep alone would
    leave the frames either side of it uncovered.  Unwinding is Rich's job
    and already correct -- ``live_context`` is a context manager, so the Live
    is torn down and the cursor restored while the exception travels.

    The exit code is ``SUCCESS`` because that is what the product's only
    other interrupt handler does (``surfaces.mcp.server.main`` returns on
    ``KeyboardInterrupt``) and because an interrupted help screen is still a
    help screen: ``--help`` exits 0, and ending it early did not fail
    anything.  Deliberately NOT 130: that would be a fifth exit code, and the
    screen right below prints the exit-code contract as a closed list.
    """

    from ..surfaces.cli.ui.help_presenter import (
        help_flag_present,
        interactive_help_requested,
        print_tour_interrupted,
    )

    if not interactive_help_requested(argv):
        return
    if not help_flag_present(argv):
        on_error("--interactive-help must be used with --help")

    try:
        from ..surfaces.cli.ui.help_tour import run_interactive_help_tour

        exit_code = run_interactive_help_tour()
    except KeyboardInterrupt:
        print_tour_interrupted()
        exit_code = int(ExitCode.SUCCESS)
    raise SystemExit(exit_code)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(
            int(ExitCode.CONTRACT_ERROR),
            f"\n  {ui.GLYPH_FAIL} CONTRACT ERROR\n    {message}\n",
        )

    def print_help(self, file: _TextWriter | None = None) -> None:
        from ..surfaces.cli.ui.help_presenter import print_static_help_mascot

        print_static_help_mascot(file=file)
        super().print_help(file=file)

    @overload
    def parse_args(
        self,
        args: Iterable[str] | None = None,
        namespace: None = None,
    ) -> argparse.Namespace: ...

    @overload
    def parse_args(
        self,
        args: Iterable[str] | None,
        namespace: _NamespaceT,
    ) -> _NamespaceT: ...

    @overload
    def parse_args(
        self,
        *,
        namespace: _NamespaceT,
    ) -> _NamespaceT: ...

    def parse_args(
        self,
        args: Iterable[str] | None = None,
        namespace: _NamespaceT | None = None,
    ) -> argparse.Namespace | _NamespaceT:
        argv = tuple(args) if args is not None else tuple(sys.argv[1:])
        _handle_interactive_help(argv, on_error=self.error)
        super_args = argv if args is not None else None
        if namespace is None:
            return super().parse_args(super_args)
        return super().parse_args(super_args, namespace)


class _HelpFormatter(argparse.RawTextHelpFormatter):
    """Product-oriented help formatter extension point."""


# argparse's generated usage spells every one of the sixty-four flags into a
# bracketed grammar: forty lines, the largest single block on the screen, and
# a strict subset of the option sections underneath it -- same flags, same
# metavars, same ``--x | --no-x`` pairs, only unreadable.  It answers "how do
# I invoke this" no better than one line does, and "which flags exist" worse
# than the grouped list does.  ``parser.error`` prints the usage too, so a
# contract error stops burying its own message under forty lines.
_USAGE = "codeclone [OPTIONS] [root]"

#: Column where help text starts, matching argparse's own two-column grid so
#: the Commands rows line up with the option rows beneath them.
_COMMAND_HELP_COLUMN = 24

_DESCRIPTION = (
    "Deterministic Structural Change Controller for AI-assisted Python development."
)


def _commands_section() -> str:
    """Render the subcommand trees as a first-screen section.

    argparse cannot generate this. The trees are dispatched by
    ``dispatch_subcommand`` before the parser is reached, so the parser holds
    no subparser action to format and its help is structurally blind to them.
    The rows are therefore built here from :data:`ui.HELP_COMMANDS`, and the
    committed help golden -- not a parser-introspection test -- is what pins
    the result, so that dropping this section is a visible diff rather than a
    test that quietly stops asserting anything.
    """

    lines = [ui.HELP_COMMANDS_TITLE]
    for name, summary in ui.HELP_COMMANDS:
        lines.append(f"  {name.ljust(_COMMAND_HELP_COLUMN - 2)}{summary}")
    return "\n".join(lines)


def _add_option(
    group: argparse._ArgumentGroup,
    *,
    option: OptionSpec,
    version: str,
) -> None:
    if option.cli_kind == "positional":
        group.add_argument(
            option.dest,
            nargs=option.nargs,
            metavar=option.metavar,
            help=option.help_text,
        )
        return

    if option.cli_kind == "value":
        if option.value_type is None:
            group.add_argument(
                *option.flags,
                dest=option.dest,
                nargs=option.nargs,
                const=option.const,
                metavar=option.metavar,
                help=option.help_text,
            )
            return
        if option.value_type is int:
            group.add_argument(
                *option.flags,
                dest=option.dest,
                nargs=option.nargs,
                const=option.const,
                metavar=option.metavar,
                type=int,
                help=option.help_text,
            )
            return
        raise RuntimeError(f"Unsupported CLI option value type: {option.value_type}")
    elif option.cli_kind == "optional_path":
        group.add_argument(
            *option.flags,
            dest=option.dest,
            nargs="?",
            const=option.const,
            metavar=option.metavar or "FILE",
            help=option.help_text,
        )
        return
    elif option.cli_kind == "bool_optional":
        group.add_argument(
            *option.flags,
            action=argparse.BooleanOptionalAction,
            default=argparse.SUPPRESS,
            help=option.help_text,
        )
        return
    elif option.cli_kind in {"store_true", "store_false"}:
        group.add_argument(
            *option.flags,
            dest=option.dest,
            action=option.cli_kind,
            default=argparse.SUPPRESS,
            help=option.help_text,
        )
        return
    elif option.cli_kind == "help":
        group.add_argument(*option.flags, action="help", help=option.help_text)
        return
    elif option.cli_kind == "version":
        group.add_argument(
            *option.flags,
            action="version",
            version=ui.version_output(version),
            help=option.help_text,
        )
        return
    else:
        raise RuntimeError(f"Unsupported CLI option kind: {option.cli_kind}")


def build_parser(version: str) -> _ArgumentParser:
    parser = _ArgumentParser(
        prog="codeclone",
        usage=_USAGE,
        description=f"{_DESCRIPTION}\n\n{_commands_section()}",
        add_help=False,
        formatter_class=_HelpFormatter,
        epilog=cli_help_epilog(),
    )

    for group_title in ARGUMENT_GROUP_TITLES:
        argument_group = parser.add_argument_group(group_title)
        for option in OPTIONS:
            if option.group != group_title or option.cli_kind is None:
                continue
            _add_option(
                argument_group,
                option=option,
                version=version,
            )

    parser.set_defaults(**DEFAULTS_BY_DEST)
    return parser


__all__ = ["_ArgumentParser", "_HelpFormatter", "build_parser"]
