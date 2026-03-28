# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal HTML skeleton template for the report.

CSS and JS are injected via ${css} and ${js} placeholders.
Body content is injected via ${body}.
"""

from __future__ import annotations

from string import Template

FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&"
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
