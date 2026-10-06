# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of the display boundary for repository text.

A file name, a qualname, a pyproject key or pattern and a memory statement are
written by whoever writes the analysed repository. Every artifact CodeClone
prints them into -- a Markdown report, a pull-request summary, a review
receipt, a text report, a terminal line, a Rich table -- would otherwise read
them as its own markup: a backtick closes a code span, a newline starts a
forged line, an escape sequence rewrites the reader's terminal, a bracket opens
a Rich tag. Each function below answers for exactly one of those channels and
the three share one control-character rule, so no emitter keeps an escaping
of its own.

Control characters are replaced, never dropped: C0 (except the tab, and the
newline where the caller's format keeps one) and DEL become the matching
Unicode control picture, C1 becomes U+FFFD. A benign name contains none of
them, a backtick or a markup bracket, so its bytes do not change.
"""

from __future__ import annotations

import re
from typing import Final

_TAB: Final = 0x09
_NEWLINE: Final = 0x0A
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
_MULTILINE: Final[dict[int, str]] = {
    code: text for code, text in _SINGLE_LINE.items() if code != _NEWLINE
}
_BACKTICK_RUN: Final = re.compile(r"`+")


def display_text(value: object, *, multiline: bool = False) -> str:
    """Return ``value`` as text a terminal or a text report prints verbatim.

    Every C0/C1 control character becomes a visible replacement, so an escape
    sequence cannot move the cursor, erase a line, open an OSC 8 link or set a
    window title, and a carriage return cannot overwrite the line it sits on.
    The tab always survives; the newline survives only for ``multiline=True``,
    where the caller's format owns line breaks (a table cell, a statement).
    """

    return str(value).translate(_MULTILINE if multiline else _SINGLE_LINE)


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


def rich_text(value: object, *, multiline: bool = False) -> str:
    """Return ``value`` escaped for interpolation into a Rich markup string.

    ``rich.markup.escape`` doubles the backslashes in front of a tag-shaped
    bracket and escapes the bracket, so ``x\\[link=...]`` stays literal text;
    it runs over :func:`display_text`, so raw escape sequences are gone before
    Rich ever sees the string, with or without colour.

    Trailing backslashes are doubled here. Rich 15.0.0 doubles one trailing
    backslash and leaves two or more alone, and a run left odd in front of the
    template's next tag escapes that tag: the template's own ``[/style]``
    became text, or ``MarkupError`` when it was a closing tag. Doubled, the run
    in front of a tag prints once and the tag stays the template's.
    """

    from rich.markup import escape

    text = display_text(value, multiline=multiline)
    trailing = len(text) - len(text.rstrip("\\"))
    escaped = escape(text)
    if trailing:
        escaped = escaped.rstrip("\\") + "\\" * (2 * trailing)
    return escaped


__all__ = ["display_text", "markdown_code", "rich_text"]
