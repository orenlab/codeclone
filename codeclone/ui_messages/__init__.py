# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""User-facing CLI messages and formatters."""

from __future__ import annotations

from .controller import *  # noqa: F403
from .formatters import *  # noqa: F403
from .help import *  # noqa: F403
from .labels import *  # noqa: F403
from .markers import *  # noqa: F403
from .runtime import *  # noqa: F403
from .styling import (  # re-export private helpers for fmt_* and tests
    _HEALTH_GRADE_STYLE as _HEALTH_GRADE_STYLE,
)
from .styling import (
    _RICH_MARKUP_TAG_RE as _RICH_MARKUP_TAG_RE,
)
from .styling import (  # the design code: grid, glyphs, semantic style map
    GLYPH_ARROW as GLYPH_ARROW,
)
from .styling import (
    GLYPH_FAIL as GLYPH_FAIL,
)
from .styling import (
    GLYPH_NONE as GLYPH_NONE,
)
from .styling import (
    GLYPH_OK as GLYPH_OK,
)
from .styling import (
    GLYPH_RULE as GLYPH_RULE,
)
from .styling import (
    GLYPH_SEP as GLYPH_SEP,
)
from .styling import (
    GLYPH_WARN as GLYPH_WARN,
)
from .styling import (
    INDENT_UNIT as INDENT_UNIT,
)
from .styling import (
    MARKUP_STYLES as MARKUP_STYLES,
)
from .styling import (
    STYLE_ACCENT as STYLE_ACCENT,
)
from .styling import (
    STYLE_COUNT_ATTENTION as STYLE_COUNT_ATTENTION,
)
from .styling import (
    STYLE_COUNT_ATTENTION_SOFT as STYLE_COUNT_ATTENTION_SOFT,
)
from .styling import (
    STYLE_COUNT_CRITICAL as STYLE_COUNT_CRITICAL,
)
from .styling import (
    STYLE_COUNT_NEUTRAL as STYLE_COUNT_NEUTRAL,
)
from .styling import (
    STYLE_EMPHASIS as STYLE_EMPHASIS,
)
from .styling import (
    STYLE_FRAME as STYLE_FRAME,
)
from .styling import (
    STYLE_FRAME_QUIET as STYLE_FRAME_QUIET,
)
from .styling import (
    STYLE_META as STYLE_META,
)
from .styling import (
    STYLE_NOTE as STYLE_NOTE,
)
from .styling import (
    STYLE_STATE_DRAFT as STYLE_STATE_DRAFT,
)
from .styling import (
    STYLE_VERDICT_FAIL as STYLE_VERDICT_FAIL,
)
from .styling import (
    STYLE_VERDICT_PASS as STYLE_VERDICT_PASS,
)
from .styling import (
    STYLE_VERDICT_PASS_STRONG as STYLE_VERDICT_PASS_STRONG,
)
from .styling import (
    STYLE_VERDICT_WARN as STYLE_VERDICT_WARN,
)
from .styling import (
    _v as _v,
)
from .styling import (
    esc as esc,
)
from .styling import (
    fmt_bool as fmt_bool,
)
from .styling import (
    n_of as n_of,
)
from .styling import (
    strip_markup as strip_markup,
)
from .styling import (
    styled as styled,
)
