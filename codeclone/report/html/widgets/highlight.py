# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Build-time syntax highlighting for the report's code and config blocks.

Highlighting happens once, when the report is written: the document ships
static spans and no highlighter, so a reader opening a saved report offline
sees the same colours as one opening it from CI.

Only real code and configuration is highlighted. The report is full of
qualnames, paths and identifiers rendered in a monospace face, and none of
them are programs -- colouring their parts would tell a reader that the
pieces mean something they do not.
"""

from __future__ import annotations

from ..primitives.escape import _escape_html
from .snippets import _try_pygments

__all__ = ["highlight_block"]


def highlight_block(code: str, *, language: str) -> str:
    """Return *code* as highlight spans, falling back to escaped text.

    The fallback is not a degraded mode worth hiding: without Pygments the
    block still renders, still copies byte-for-byte, and still reads as code
    because the surrounding ``.codebox`` carries the monospace face. Only the
    colour is missing.
    """

    highlighted = _try_pygments(code, language=language)
    if highlighted is None:
        return _escape_html(code)
    return highlighted.rstrip("\n")
