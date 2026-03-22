# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Public facade for HTML report generation.

Re-exports build_html_report from the new _html_report package and
keeps backward-compatible imports that tests and downstream code rely on.
"""

from __future__ import annotations

from ._html_report import build_html_report
from ._html_snippets import (
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
