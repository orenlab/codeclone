# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal HTML skeleton template for the report.

CSS and JS are injected via ${css} and ${js} placeholders.
Body content is injected via ${body}. The page loads nothing from the
network: the CSS font stacks name Inter and JetBrains Mono only as locally
installed fonts and fall back to the system fonts.
"""

from __future__ import annotations

from string import Template

REPORT_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en" data-scan-root="${scan_root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>${css}</style>
</head>
<body>
${body}
<script>${js}</script>
</body>
</html>"""
)

__all__ = [
    "REPORT_TEMPLATE",
]
