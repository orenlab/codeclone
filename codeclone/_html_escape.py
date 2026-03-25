# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import html


def _escape_html(v: object) -> str:
    text = html.escape("" if v is None else str(v), quote=True)
    text = text.replace("`", "&#96;")
    text = text.replace("\u2028", "&#8232;").replace("\u2029", "&#8233;")
    return text


def _escape_attr(v: object) -> str:
    text = html.escape("" if v is None else str(v), quote=True)
    text = text.replace("`", "&#96;")
    text = text.replace("\u2028", "&#8232;").replace("\u2029", "&#8233;")
    return text


def _meta_display(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "n/a"
    text = str(v).strip()
    return text if text else "n/a"
