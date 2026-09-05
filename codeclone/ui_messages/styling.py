# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The CLI design code: one grid, one style map, one glyph vocabulary.

This module is the single owner of terminal presentation decisions.
Renderers import semantics from here; they never restate them locally.

The rules, enforced mechanically by ``tests/test_cli_design_system.py``:

* Indentation moves in :data:`INDENT_UNIT` steps; block labels pad to
  :data:`_L` columns.
* Chromatic color words appear only in this file. Everything else styles
  through the semantic ``STYLE_*`` constants — color states a verdict
  (pass, fail, warn) or an owned count role, never decoration.
* Glyphs come from the vocabulary below; no renderer invents its own.
* Counts render with thousands separators via :func:`_v`; nouns agree in
  number via :func:`n_of`.
* Dynamic text interpolated into markup is escaped with :func:`esc` so
  bracketed payload data (``[Errno 2]``, severity markers) survives
  rendering byte-for-byte.
* Messages are stripped of markup only through :func:`strip_markup`,
  which removes exactly the tags of the style map and nothing else.
"""

from __future__ import annotations

import re

from ..domain.quality import (
    HEALTH_GRADE_A,
    HEALTH_GRADE_B,
    HEALTH_GRADE_C,
    HEALTH_GRADE_D,
    HEALTH_GRADE_F,
)

# ── layout grid ──────────────────────────────────────────────────────

INDENT_UNIT = 2
# Label column width (after the 2-space indent). Even, so that the value
# column it opens (INDENT_UNIT + _L) is itself on the grid: a continuation
# hung under a value lands on a grid column, not one past it.
_L = 14

# ── glyph vocabulary ─────────────────────────────────────────────────

GLYPH_OK = "✔"  # ✔ verdict-pass marker
GLYPH_FAIL = "✗"  # ✗ verdict-fail marker
GLYPH_WARN = "⚠"  # ⚠ advisory marker
GLYPH_SEP = "·"  # · value separator inside a row
GLYPH_ARROW = "→"  # → before/after transition
GLYPH_RULE = "─"  # ─ section rule character
GLYPH_NONE = "—"  # — absent value in tables

# ── semantic style map ───────────────────────────────────────────────
# The only place in the CLI where raw color words may appear. Verdict
# colors are reserved for verdict states; count roles are reserved for
# counts of the matching class; neutral magnitudes never borrow them.

STYLE_VERDICT_PASS = "green"  # clean states (✔ clean)
STYLE_VERDICT_PASS_STRONG = "bold green"  # top-grade and accepted verdicts
STYLE_VERDICT_FAIL = "bold red"  # failure verdicts and gate failures
STYLE_VERDICT_WARN = "yellow"  # advisory verdict states
STYLE_COUNT_NEUTRAL = "bold cyan"  # neutral magnitudes (files, lines)
STYLE_COUNT_ATTENTION = "bold yellow"  # finding counts (clone groups)
STYLE_COUNT_ATTENTION_SOFT = "yellow"  # qualifier finding counts (suppressed)
STYLE_COUNT_CRITICAL = "bold red"  # gate-relevant counts (new, breaking)
STYLE_ACCENT = "cyan"  # identifiers and query echoes
STYLE_EMPHASIS = "bold"  # structural emphasis (labels, names)
STYLE_META = "dim"  # secondary facts, paths, hints
STYLE_NOTE = "dim italic"  # inline advisory notes
STYLE_FRAME = "cyan"  # primary panel borders
STYLE_FRAME_QUIET = "dim"  # secondary panel borders
STYLE_STATE_DRAFT = "magenta"  # unapproved governance state (memory drafts)

_HEALTH_GRADE_STYLE: dict[str, str] = {
    HEALTH_GRADE_A: STYLE_VERDICT_PASS_STRONG,
    HEALTH_GRADE_B: STYLE_VERDICT_PASS,
    HEALTH_GRADE_C: STYLE_VERDICT_WARN,
    HEALTH_GRADE_D: STYLE_VERDICT_FAIL,
    HEALTH_GRADE_F: STYLE_VERDICT_FAIL,
}

# The Rich console theme: message roles resolved to semantic styles.
# ``cli.console`` builds its Console from this mapping.
RICH_THEME_STYLES: dict[str, str] = {
    "info": STYLE_ACCENT,
    "warning": STYLE_VERDICT_WARN,
    "error": STYLE_VERDICT_FAIL,
    "success": STYLE_VERDICT_PASS_STRONG,
    "dim": STYLE_META,
    "codeclone.primary": STYLE_ACCENT,
    "codeclone.muted": STYLE_META,
    "codeclone.success": STYLE_VERDICT_PASS_STRONG,
    "codeclone.attention": STYLE_VERDICT_WARN,
}

# Named message roles from the Rich theme (see cli.console) plus the
# style constants above. ``strip_markup`` removes exactly these tags.
MARKUP_STYLES: frozenset[str] = frozenset(
    {
        "info",
        "warning",
        "error",
        "success",
        "codeclone.primary",
        "codeclone.muted",
        "codeclone.success",
        "codeclone.attention",
        STYLE_VERDICT_PASS,
        STYLE_VERDICT_PASS_STRONG,
        STYLE_VERDICT_FAIL,
        STYLE_VERDICT_WARN,
        STYLE_COUNT_NEUTRAL,
        STYLE_COUNT_ATTENTION,
        STYLE_COUNT_ATTENTION_SOFT,
        STYLE_COUNT_CRITICAL,
        STYLE_ACCENT,
        STYLE_EMPHASIS,
        STYLE_META,
        STYLE_NOTE,
    }
)

_RICH_MARKUP_TAG_RE = re.compile(
    r"\[/?(?:" + "|".join(sorted(re.escape(tag) for tag in MARKUP_STYLES)) + r")\]"
)


def esc(value: object) -> str:
    """Escape dynamic text for safe interpolation into markup strings.

    Rich treats any well-formed ``[word]`` as a style tag and silently
    swallows it. Payload data — error details, severity markers, literal
    brackets — must pass through :func:`esc` before entering a markup
    template so it survives rendering unmodified.
    """

    return str(value).replace("[", "\\[")


def strip_markup(text: str) -> str:
    """Remove design-code markup tags and unescape payload brackets.

    Only tags from :data:`MARKUP_STYLES` are removed; bracketed payload
    data such as ``[Errno 2]`` is left intact. Escaped brackets produced
    by :func:`esc` are restored to literal brackets.
    """

    return _RICH_MARKUP_TAG_RE.sub("", text).replace("\\[", "[")


def styled(text: object, style: str) -> str:
    """Wrap ``text`` in one semantic style tag pair."""

    return f"[{style}]{text}[/{style}]"


def n_of(count: int, singular: str, plural: str | None = None) -> str:
    """Format a count with its noun, separator-grouped and number-agreed."""

    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count:,} {noun}"


def fmt_bool(value: object) -> str:
    """Render a boolean fact as ``yes`` / ``no`` (never raw ``True``)."""

    return "yes" if value else "no"


def _v(n: int, style: str = "") -> str:
    """Format a count: separator-grouped, dim if zero, styled otherwise."""

    match (n == 0, bool(style)):
        case (True, _):
            return f"[{STYLE_META}]{n}[/{STYLE_META}]"
        case (False, True):
            return f"[{style}]{n:,}[/{style}]"
        case _:
            return f"{n:,}"


def _format_permille_pct(value: int) -> str:
    return f"{value / 10.0:.1f}%"
