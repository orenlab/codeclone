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
from .mascot import Aster, mascot_use_unicode
from .mascot_frames import AsterState


class TextWriter(Protocol):
    def write(self, text: str, /) -> object: ...


def help_flag_present(argv: Sequence[str]) -> bool:
    return any(token in {"-h", "--help"} for token in argv)


def interactive_help_requested(argv: Sequence[str]) -> bool:
    return "--interactive-help" in argv


def static_help_mascot_lines(*, use_unicode: bool | None = None) -> tuple[str, ...]:
    unicode = mascot_use_unicode() if use_unicode is None else use_unicode
    aster = Aster(AsterState.IDLE, use_unicode=unicode)
    lines = list(aster.plain_lines())
    lines.append(help_ui.HELP_MASCOT_TAGLINE)
    return tuple(lines)


def print_static_help_mascot(*, file: TextWriter | None = None) -> None:
    target = file if file is not None else sys.stdout
    for line in static_help_mascot_lines():
        print(line, file=target)
    print("", file=target)


__all__ = [
    "help_flag_present",
    "interactive_help_requested",
    "print_static_help_mascot",
    "static_help_mascot_lines",
]
