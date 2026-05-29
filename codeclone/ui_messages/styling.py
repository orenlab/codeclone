# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared Rich formatting helpers for CLI output."""

from __future__ import annotations

import re

from ..domain.quality import (
    HEALTH_GRADE_A,
    HEALTH_GRADE_B,
    HEALTH_GRADE_C,
    HEALTH_GRADE_D,
    HEALTH_GRADE_F,
)

_RICH_MARKUP_TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_ .#:-]*]")
_HEALTH_GRADE_STYLE: dict[str, str] = {
    HEALTH_GRADE_A: "bold green",
    HEALTH_GRADE_B: "green",
    HEALTH_GRADE_C: "yellow",
    HEALTH_GRADE_D: "bold red",
    HEALTH_GRADE_F: "bold red",
}

_L = 13  # label column width (after 2-space indent)


def _v(n: int, style: str = "") -> str:
    """Format value: dim if zero, styled otherwise."""
    match (n == 0, bool(style)):
        case (True, _):
            return f"[dim]{n}[/dim]"
        case (False, True):
            return f"[{style}]{n}[/{style}]"
        case _:
            return str(n)


def _vn(n: int, style: str = "") -> str:
    """Format value with comma separator: dim if zero, styled otherwise."""
    match (n == 0, bool(style)):
        case (True, _):
            return f"[dim]{n:,}[/dim]"
        case (False, True):
            return f"[{style}]{n:,}[/{style}]"
        case _:
            return f"{n:,}"


def _format_permille_pct(value: int) -> str:
    return f"{value / 10.0:.1f}%"
