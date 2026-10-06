# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one human spelling of a comparison delta.

The maintainer's ruling (2026-10-03)::

    comparison performed     -> integer, including 0
    comparison not performed -> null

Machine surfaces state ``null``; a human surface never prints the literal,
nor a number, nor nothing: it prints these words.  Every human surface of a
comparison delta -- the HTML report, the CLI summary, and every renderer
after it -- spells the value through this module, so the words are the same
everywhere and a measured zero stays ``0``.  The surface only chooses the
label it prints beside the value; whether the comparison ran is the value
itself (``None``), read off the normalized comparison state.
"""

from __future__ import annotations

from typing import Final

#: The words for a delta whose comparison did not run.
NOT_COMPARED: Final = "not compared"
#: The same words where a compact ``key=value`` line holds the value.
NOT_COMPARED_COMPACT: Final = "n/a (not compared)"


def _number(value: int, *, signed: bool) -> str:
    if signed and value:
        return f"{value:+d}"
    return str(value)


def comparison_text(value: int | None, *, signed: bool = False) -> str:
    """A delta for a sentence or a card: its number (``+3`` / ``-2`` when
    ``signed``; a measured zero is ``0``, never ``+0``), or ``not compared``."""
    return NOT_COMPARED if value is None else _number(value, signed=signed)


def comparison_text_compact(value: int | None, *, signed: bool = False) -> str:
    """A delta for a compact ``key=value`` line: its number, or
    ``n/a (not compared)``."""
    return NOT_COMPARED_COMPACT if value is None else _number(value, signed=signed)


__all__ = [
    "NOT_COMPARED",
    "NOT_COMPARED_COMPACT",
    "comparison_text",
    "comparison_text_compact",
]
