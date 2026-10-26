# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of the display boundary for repository text.

A file name or a qualname is written by whoever writes the analysed
repository. A Markdown report or a pull-request summary would otherwise read it
as its own markup: a backtick closes a code span and lets the rest render as
live HTML, a newline starts a forged line such as a verdict heading. The two
functions below share one control-character rule, so no emitter keeps an
escaping of its own.

Control characters are replaced, never dropped: C0 (except the tab) and DEL
become the matching Unicode control picture, C1 becomes U+FFFD. A benign name
contains none of them and no backtick, so its bytes do not change.
"""

from __future__ import annotations

import re
from typing import Final

_TAB: Final = 0x09
_DELETE: Final = 0x7F
_CONTROL_PICTURES_BASE: Final = 0x2400
_DELETE_PICTURE: Final = "␡"
_C1_REPLACEMENT: Final = "�"


def _replacement(code: int) -> str:
    if code < 0x20:
        return chr(_CONTROL_PICTURES_BASE + code)
    if code == _DELETE:
        return _DELETE_PICTURE
    return _C1_REPLACEMENT


_CONTROL_CODES: Final = (*range(0x20), _DELETE, *range(0x80, 0xA0))
_SINGLE_LINE: Final[dict[int, str]] = {
    code: _replacement(code) for code in _CONTROL_CODES if code != _TAB
}
_BACKTICK_RUN: Final = re.compile(r"`+")


def display_text(value: object) -> str:
    """Return ``value`` as one line of text that is printed verbatim.

    Every C0/C1 control character becomes a visible replacement, so a newline
    cannot start a forged line, an escape sequence cannot move the cursor or
    erase a line, and a carriage return cannot overwrite the line it sits on.
    The tab survives.
    """

    return str(value).translate(_SINGLE_LINE)


def markdown_code(value: object) -> str:
    """Return ``value`` as one inert Markdown inline code span.

    The fence is one backtick longer than the longest backtick run inside the
    text, so no run inside can close it; a span that would start or end with a
    backtick, or whose both ends are spaces, is padded with one space each side,
    which CommonMark strips again. Newlines and every other control character
    are replaced first (:func:`display_text`), so the span cannot be ended by a
    blank line and nothing after it is read as a new line of the document.
    """

    text = display_text(value)
    longest = max((len(run) for run in _BACKTICK_RUN.findall(text)), default=0)
    fence = "`" * (longest + 1)
    padded = (
        text.startswith("`")
        or text.endswith("`")
        or (text.startswith(" ") and text.endswith(" ") and bool(text.strip(" ")))
    )
    if padded:
        text = f" {text} "
    return f"{fence}{text}{fence}"


__all__ = ["display_text", "markdown_code"]
