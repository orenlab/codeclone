# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical HTML report package."""

from __future__ import annotations

from .assemble import build_html_report
from .widgets.snippets import (
    _FileCache,
    _pygments_css,
    _render_code_block,
    _try_pygments,
)

__all__ = [
    "_FileCache",
    "_pygments_css",
    "_render_code_block",
    "_try_pygments",
    "build_html_report",
]
