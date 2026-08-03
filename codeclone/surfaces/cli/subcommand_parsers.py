# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Declarative argparse scaffolding for repository-scoped CLI subcommands.

``codeclone memory`` and ``codeclone analytics`` expose trees of argparse
subcommands where every command is opened the same way: create the subparser,
attach the repository ``--root`` option, then attach a handful of options drawn
from a small recurring vocabulary (``--limit``, ``--json``, a positional, a
boolean flag). Written out by hand that shape repeated dozens of times, which is
what the clone lanes reported as duplicated parser scaffolding.

The dissolution is deliberately *declarative* rather than merely factored:

* :func:`build_root_commands` is the single place that knows how to turn a
  command declaration into a parser. Callers describe commands as data.
* An option is an :data:`OptionApplier` — a callable that attaches one argument
  to a parser. The recurring options have named builders below; genuinely
  one-off options are inline lambdas at the call site.

An earlier attempt kept the registrations imperative and only extracted the
common lines into helper functions. That moved the duplication instead of
removing it: the *sequence* of calls per command stayed identical, and the clone
lanes correctly reported new duplicate blocks among the new helpers. Only making
the commands data removes the repeated shape, so prefer extending the vocabulary
here over hand-writing another registration sequence.

Registration order is preserved exactly: argparse renders help in the order
arguments are added, so a command's options are applied in declaration order.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Protocol

OptionApplier = Callable[[argparse.ArgumentParser], None]
"""Attaches exactly one argument to a parser."""

CommandDeclaration = tuple[str, str, Sequence[OptionApplier]]
"""One subcommand as ``(name, help text, options applied in order)``."""


class SubparserRegistry(Protocol):
    """The ``add_subparsers()`` action surface needed to open one subcommand."""

    def add_parser(self, name: str, *, help: str) -> argparse.ArgumentParser: ...


def add_root_command(
    registry: SubparserRegistry,
    name: str,
    *,
    help_text: str,
    root_help: str,
) -> argparse.ArgumentParser:
    """Open a subcommand that operates on a repository root.

    Returns the new parser with ``--root`` already attached. ``root_help`` is
    required rather than defaulted because the surfaces publish different help
    text for the option, and unifying it would change user-visible output.
    """

    parser = registry.add_parser(name, help=help_text)
    parser.add_argument("--root", default=".", help=root_help)
    return parser


def build_root_commands(
    registry: SubparserRegistry,
    *,
    root_help: str,
    commands: Sequence[CommandDeclaration],
) -> None:
    """Materialize a table of repository-scoped subcommands, in table order."""

    for name, help_text, options in commands:
        parser = add_root_command(
            registry,
            name,
            help_text=help_text,
            root_help=root_help,
        )
        for apply_option in options:
            apply_option(parser)


def add_command_group(
    registry: SubparserRegistry,
    name: str,
    *,
    help_text: str,
    dest: str,
) -> SubparserRegistry:
    """Open a nested command group and return its registry for child commands.

    The group parser itself takes no ``--root``; the repository root belongs to
    the leaf commands that actually act on it.
    """

    group_parser = registry.add_parser(name, help=help_text)
    return group_parser.add_subparsers(dest=dest, required=True)


def flag_option(name: str, *, help_text: str | None = None) -> OptionApplier:
    """Build an applier attaching a boolean ``store_true`` flag."""

    def apply(parser: argparse.ArgumentParser) -> None:
        if help_text is None:
            parser.add_argument(name, action="store_true")
        else:
            parser.add_argument(name, action="store_true", help=help_text)

    return apply


def json_option(*, help_text: str | None = None) -> OptionApplier:
    """Build an applier attaching the standard ``--json`` machine-output flag."""

    return flag_option("--json", help_text=help_text)


def limit_option(*, default: int) -> OptionApplier:
    """Build an applier attaching the standard bounded-result ``--limit``."""

    def apply(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--limit", type=int, default=default)

    return apply


def value_option(
    name: str,
    *,
    help_text: str | None = None,
    metavar: str | None = None,
    dest: str | None = None,
    required: bool = False,
) -> OptionApplier:
    """Build an applier attaching one string-valued optional argument.

    Every parameter defaults to argparse's own default, so passing none of them
    is equivalent to a bare ``add_argument(name)``.
    """

    def apply(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            name,
            help=help_text,
            metavar=metavar,
            dest=dest,
            required=required,
        )

    return apply


def positional_option(
    name: str,
    *,
    help_text: str | None = None,
    nargs: str | None = None,
) -> OptionApplier:
    """Build an applier attaching one positional argument."""

    def apply(parser: argparse.ArgumentParser) -> None:
        if nargs is not None and help_text is not None:
            parser.add_argument(name, nargs=nargs, help=help_text)
        elif help_text is not None:
            parser.add_argument(name, help=help_text)
        else:
            parser.add_argument(name)

    return apply


__all__ = [
    "CommandDeclaration",
    "OptionApplier",
    "SubparserRegistry",
    "add_command_group",
    "add_root_command",
    "build_root_commands",
    "flag_option",
    "json_option",
    "limit_option",
    "positional_option",
    "value_option",
]
