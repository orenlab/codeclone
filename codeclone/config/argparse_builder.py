# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from .. import ui_messages as ui
from ..contracts import ExitCode, cli_help_epilog
from .spec import ARGUMENT_GROUP_TITLES, DEFAULTS_BY_DEST, OPTIONS, OptionSpec


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(
            int(ExitCode.CONTRACT_ERROR),
            f"CONTRACT ERROR: {message}\n",
        )


class _HelpFormatter(argparse.RawTextHelpFormatter):
    """Product-oriented help formatter extension point."""


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
        description="Structural code quality analysis for Python.",
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
