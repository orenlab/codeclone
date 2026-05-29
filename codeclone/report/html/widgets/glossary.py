# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""HTML glossary tooltip helper."""

from __future__ import annotations

from ...messages.glossary import GLOSSARY
from ..primitives.escape import _escape_html


def glossary_tip(label: str) -> str:
    """Return a tooltip ``<span>`` for *label*, or ``''`` if unknown."""
    tip = GLOSSARY.get(label.lower(), "")
    if not tip:
        return ""
    return f' <span class="kpi-help" data-tip="{_escape_html(tip)}">?</span>'
