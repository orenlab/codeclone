# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Static help banner for ``codeclone --help``."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Protocol

from ....ui_messages import help as help_ui
from .mascot import Aster, mascot_use_unicode, product_identity
from .mascot_frames import AsterState


class TextWriter(Protocol):
    def write(self, text: str, /) -> object: ...


def help_flag_present(argv: Sequence[str]) -> bool:
    return any(token in {"-h", "--help"} for token in argv)


def interactive_help_requested(argv: Sequence[str]) -> bool:
    return "--interactive-help" in argv


def static_help_mascot_lines(*, use_unicode: bool | None = None) -> tuple[str, ...]:
    """The help banner: the mascot, the product's name, one tagline.

    ``message=product_identity()`` is what makes this ONE self-description.
    The idle frame carries its own message for the run screen -- "Deterministic
    structural change control." -- and the banner used to print that beside the
    identity, so the first line of ``--help`` said "structural change control"
    twice, two spaces apart.  The frame message belongs to the run; the
    product's name belongs to the screen that introduces it.
    """

    unicode = mascot_use_unicode() if use_unicode is None else use_unicode
    aster = Aster(AsterState.IDLE, message=product_identity(), use_unicode=unicode)
    lines = list(aster.plain_lines())
    lines.append(help_ui.HELP_MASCOT_TAGLINE)
    return tuple(lines)


def print_tour_interrupted(*, file: TextWriter | None = None) -> None:
    """One line for a reader who ended the tour with Ctrl+C.

    It answers the only question left at that moment -- where the rest of what
    the tour was going to say now lives -- and says nothing else.
    """

    target = file if file is not None else sys.stdout
    print("", file=target)
    print(help_ui.HELP_TOUR_INTERRUPTED, file=target)


def print_static_help_mascot(*, file: TextWriter | None = None) -> None:
    target = file if file is not None else sys.stdout
    for line in static_help_mascot_lines():
        print(line, file=target)
    print("", file=target)


__all__ = [
    "help_flag_present",
    "interactive_help_requested",
    "print_static_help_mascot",
    "print_tour_interrupted",
    "static_help_mascot_lines",
]
