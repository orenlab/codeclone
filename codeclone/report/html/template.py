# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal HTML skeleton template for the report.

CSS and JS are injected via ${css} and ${js} placeholders.
Body content is injected via ${body}.
"""

from __future__ import annotations

from string import Template

FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2?"
    # Inter Variable — single file, full weight axis (100..900), smoother
    # rendering than static cuts. Used for body text AND display (KPI numbers,
    # headings). Google Fonts' Inter Tight subset drops the `zero` OT feature,
    # so we stick to a single Inter family and apply display weight/tracking
    # via CSS instead of a sibling family.
    "family=Inter:wght@100..900&"
    # JetBrains Mono — code/monospace surfaces.
    "family=JetBrains+Mono:wght@400;500&"
    "display=swap"
)

REPORT_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en" data-scan-root="${scan_root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="${font_css_url}" rel="stylesheet">
<style>${css}</style>
</head>
<body>
${body}
<script>${js}</script>
</body>
</html>"""
)

__all__ = [
    "FONT_CSS_URL",
    "REPORT_TEMPLATE",
]
