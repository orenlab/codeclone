# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""HTML glossary tooltip helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...messages.glossary import glossary_term
from ..primitives.escape import _escape_html

if TYPE_CHECKING:
    from collections.abc import Callable


def glossary_tip(label: str, *, family: str) -> str:
    """Return a tooltip ``<span>`` for *label* as *family* reads it.

    *family* is required: the same word means different things in different
    panels, and a caller that cannot say which panel it is has no business
    answering for the word.
    """
    tip = glossary_term(label, family=family)
    if not tip:
        return ""
    return f' <span class="kpi-help" data-tip="{_escape_html(tip)}">?</span>'


def family_glossary_tip(family: str) -> Callable[[str], str]:
    """Bind *family* once for callers that hand the tip helper on by name.

    Stat cards take the helper as ``glossary_tip_fn`` and call it with a label
    alone, so the family has to be attached before it travels.
    """

    def _tip(label: str) -> str:
        return glossary_tip(label, family=family)

    return _tip


__all__ = ["family_glossary_tip", "glossary_tip"]
